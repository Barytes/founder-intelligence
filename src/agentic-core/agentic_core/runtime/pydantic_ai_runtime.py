from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import json
from threading import Thread
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlparse

import httpx
from opentelemetry.trace import TracerProvider
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic_ai import Agent, ToolDefinition, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings, InstrumentedModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_ai.usage import RunUsage

from agentic_core.messages import normalize_messages
from agentic_core.schemas import AgenticConfig, ProviderConfig, RunResult, ToolCallLog
from agentic_core.tools.registry import ToolRegistry


OutputT = TypeVar("OutputT")
_DICT_VALIDATOR = TypeAdapter(dict[str, Any]).validator


class RuntimeBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_limit: int = Field(default=8, ge=1)
    tool_calls_limit: int | None = Field(default=None, ge=0)
    input_tokens_limit: int | None = Field(default=None, ge=1)
    output_tokens_limit: int | None = Field(default=None, ge=1)
    total_tokens_limit: int | None = Field(default=None, ge=1)

    def as_usage_limits(self) -> UsageLimits:
        return UsageLimits(**self.model_dump())


class RuntimeTraceEvent(BaseModel):
    """Auditable framework-neutral projection of model and tool events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    kind: str
    name: str | None = None
    call_id: str | None = None
    content: Any | None = None


class RuntimeResult(BaseModel, Generic[OutputT]):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error"]
    output: OutputT | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    trace_events: list[RuntimeTraceEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass
class RuntimeDependencies:
    registry: ToolRegistry
    context: dict[str, Any]
    tool_logs: list[ToolCallLog] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)


class RegistryToolset(AbstractToolset[RuntimeDependencies]):
    """Expose ToolRegistry schemas without bypassing its local permission checks."""

    @property
    def id(self) -> str:
        return "founder-intelligence-registry"

    async def get_tools(
        self, _ctx: Any
    ) -> dict[str, ToolsetTool[RuntimeDependencies]]:
        tools: dict[str, ToolsetTool[RuntimeDependencies]] = {}
        for definition in self._registry.enabled_tools():
            tool_def = ToolDefinition(
                name=definition.name,
                description=definition.description,
                parameters_json_schema=definition.parameters,
            )
            tools[definition.name] = ToolsetTool(
                toolset=self,
                tool_def=tool_def,
                max_retries=0,
                args_validator=_DICT_VALIDATOR,
            )
        return tools

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        _tool: ToolsetTool[RuntimeDependencies],
    ) -> Any:
        log = ToolCallLog(name=name, arguments=tool_args)
        try:
            result = ctx.deps.registry.run(name, tool_args, ctx.deps.context)
            log.result = result
            if isinstance(result, dict):
                paths = result.get("artifact_paths")
                if isinstance(paths, list):
                    ctx.deps.artifact_paths.extend(
                        str(path) for path in paths if isinstance(path, str)
                    )
            return result
        except Exception as exc:
            log.error = str(exc)
            return f"ERROR: {exc}"
        finally:
            ctx.deps.tool_logs.append(log)


def build_openai_compatible_model(
    config: ProviderConfig,
    *,
    timeout_seconds: float = 60,
    http_client: httpx.AsyncClient | None = None,
) -> OpenAIChatModel:
    """Build the only provider-specific object used by the runtime adapter."""

    if not config.api_key:
        raise ValueError(f"missing API key env var: {config.api_key_env}")
    provider = OpenAIProvider(
        base_url=config.base_url or config.default_base_url,
        api_key=config.api_key,
        http_client=http_client or httpx.AsyncClient(timeout=timeout_seconds),
    )
    return OpenAIChatModel(config.model, provider=provider)


def _model_settings(config: AgenticConfig) -> dict[str, Any]:
    settings: dict[str, Any] = {"temperature": config.agent.temperature}
    provider_url = config.provider.base_url or config.provider.default_base_url
    if (
        config.provider.model.startswith("deepseek-v4-")
        and urlparse(provider_url).hostname == "api.deepseek.com"
    ):
        settings["extra_body"] = {"thinking": {"type": "disabled"}}
    return settings


def _prompt_from_messages(messages: list[dict[str, Any]]) -> str:
    normalized = normalize_messages(messages)
    return "\n".join(f"[{message['role']}] {message['content']}" for message in normalized)


def _usage_dict(usage: Any) -> dict[str, Any]:
    values = {key: value for key, value in asdict(usage).items() if value not in (0, {}, None)}
    values["total_tokens"] = usage.input_tokens + usage.output_tokens
    return values


def _trace_events(messages: list[Any]) -> list[RuntimeTraceEvent]:
    events: list[RuntimeTraceEvent] = []
    for message in messages:
        for part in message.parts:
            kind = str(getattr(part, "part_kind", part.__class__.__name__))
            content = getattr(part, "content", None)
            if content is None:
                content = getattr(part, "args", None)
            if "thinking" in kind or "reasoning" in kind:
                content = "[redacted]"
            events.append(
                RuntimeTraceEvent(
                    sequence=len(events) + 1,
                    kind=kind,
                    name=getattr(part, "tool_name", None),
                    call_id=getattr(part, "tool_call_id", None),
                    content=content,
                )
            )
    return events


def _compatibility_messages(
    initial: list[dict[str, Any]], trace_events: list[RuntimeTraceEvent]
) -> list[dict[str, Any]]:
    conversation = list(initial)
    for event in trace_events:
        if event.kind == "tool-call" and event.name:
            call = {
                "id": event.call_id or event.name,
                "type": "function",
                "function": {
                    "name": event.name,
                    "arguments": json.dumps(event.content or {}, ensure_ascii=False),
                },
            }
            if (
                conversation
                and conversation[-1].get("role") == "assistant"
                and conversation[-1].get("content") == ""
                and "tool_calls" in conversation[-1]
            ):
                conversation[-1]["tool_calls"].append(call)
            else:
                conversation.append(
                    {"role": "assistant", "content": "", "tool_calls": [call]}
                )
        elif event.kind == "tool-return" and event.name:
            content = event.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": event.call_id or event.name,
                    "name": event.name,
                    "content": content,
                }
            )
        elif event.kind == "text" and isinstance(event.content, str):
            conversation.append({"role": "assistant", "content": event.content})
    return conversation


class PydanticAIRuntime:
    """Bounded PydanticAI adapter; framework types do not escape this module."""

    def __init__(
        self,
        *,
        config: AgenticConfig,
        tools: ToolRegistry,
        model: Model | None = None,
        tracer_provider: TracerProvider | None = None,
        retries: int = 1,
    ):
        self.config = config
        self.tools = tools
        self._owned_model: OpenAIChatModel | None = None
        if model is None:
            self._owned_model = build_openai_compatible_model(
                config.provider,
                timeout_seconds=config.agent.timeout_seconds,
            )
            selected_model: Model = self._owned_model
        else:
            selected_model = model
        if tracer_provider is not None:
            selected_model = InstrumentedModel(
                selected_model,
                InstrumentationSettings(tracer_provider=tracer_provider),
            )
        self.model = selected_model
        self.retries = retries

    async def aclose(self) -> None:
        """Close the provider client only when this adapter created it."""

        if self._owned_model is not None:
            await self._owned_model.client.close()

    def close(self) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            error: list[BaseException] = []

            def close_in_thread() -> None:
                try:
                    asyncio.run(self.aclose())
                except BaseException as exc:  # pragma: no cover - forwarded below
                    error.append(exc)

            thread = Thread(target=close_in_thread, daemon=True)
            thread.start()
            thread.join()
            if error:
                raise error[0]
            return
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:  # sync worker threads may not have a loop yet
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(self.aclose())

    def run_typed(
        self,
        *,
        messages: list[dict[str, Any]],
        output_type: type[OutputT],
        context: dict[str, Any] | None = None,
        budget: RuntimeBudget | None = None,
    ) -> RuntimeResult[OutputT]:
        deps = RuntimeDependencies(self.tools, dict(context or {}))
        limits = budget or RuntimeBudget(request_limit=self.config.agent.max_turns)
        agent = Agent(
            self.model,
            output_type=output_type,
            deps_type=RuntimeDependencies,
            system_prompt=self.config.agent.system_prompt,
            retries=self.retries,
            toolsets=[RegistryToolset(self.tools)],
            model_settings=_model_settings(self.config),
        )
        captured_messages: list[Any]
        run_usage = RunUsage()
        try:
            with capture_run_messages() as captured_messages:
                result = agent.run_sync(
                    _prompt_from_messages(messages),
                    deps=deps,
                    usage_limits=limits.as_usage_limits(),
                    usage=run_usage,
                )
        except (UsageLimitExceeded, UnexpectedModelBehavior) as exc:
            return RuntimeResult[OutputT](
                status="error",
                usage=_usage_dict(run_usage),
                tool_calls=deps.tool_logs,
                artifact_paths=deps.artifact_paths,
                trace_events=_trace_events(captured_messages),
                errors=[f"{exc.__class__.__name__}: {exc}"],
            )
        except Exception as exc:
            return RuntimeResult[OutputT](
                status="error",
                usage=_usage_dict(run_usage),
                tool_calls=deps.tool_logs,
                artifact_paths=deps.artifact_paths,
                trace_events=_trace_events(captured_messages),
                errors=[f"{exc.__class__.__name__}: {exc}"],
            )

        return RuntimeResult[OutputT](
            status="ok",
            output=result.output,
            usage=_usage_dict(result.usage),
            tool_calls=deps.tool_logs,
            artifact_paths=deps.artifact_paths,
            trace_events=_trace_events(result.all_messages()),
        )

    def run(
        self,
        *,
        messages: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        typed = self.run_typed(
            messages=messages,
            output_type=str,
            context=context,
        )
        initial = [
            {"role": "system", "content": self.config.agent.system_prompt},
            *normalize_messages(messages),
        ]
        conversation = _compatibility_messages(initial, typed.trace_events)
        if typed.status == "ok":
            final_text = str(typed.output or "")
            if not conversation or conversation[-1] != {
                "role": "assistant",
                "content": final_text,
            }:
                conversation.append({"role": "assistant", "content": final_text})
            return RunResult(
                status="ok",
                messages=conversation,
                final_text=final_text,
                tool_calls=typed.tool_calls,
                artifact_paths=typed.artifact_paths,
                usage=typed.usage,
            )
        return RunResult(
            status="error",
            messages=conversation,
            tool_calls=typed.tool_calls,
            artifact_paths=typed.artifact_paths,
            usage=typed.usage,
            errors=(
                ["max turns reached"]
                if any("UsageLimitExceeded" in error for error in typed.errors)
                else typed.errors
            ),
        )
