import json
from pathlib import Path
from typing import Any

from agentic_core.config import load_agentic_config
from agentic_core.messages import normalize_messages
from agentic_core.providers import build_provider
from agentic_core.providers.base import Provider
from agentic_core.schemas import AgenticConfig, RunResult, ToolCallLog
from agentic_core.tools import build_default_registry
from agentic_core.tools.registry import ToolRegistry


class AgenticCore:
    """Callable Agentic Core component."""

    def __init__(
        self,
        config: AgenticConfig,
        provider: Provider | None = None,
        tools: ToolRegistry | None = None,
    ):
        self.config = config
        self.provider = (
            provider
            if provider is not None
            else build_provider(
                config.provider,
                timeout_seconds=config.agent.timeout_seconds,
            )
        )
        self.tools = tools or build_default_registry(config.tools)

    @classmethod
    def from_config(cls, config_path: str | Path) -> "AgenticCore":
        return cls(load_agentic_config(config_path))

    def _default_context(self) -> dict[str, str]:
        return {
            "signals_path": str(self.config.paths.signals),
            "canonical_items_path": str(self.config.paths.canonical_items),
            "artifact_dir": str(self.config.paths.artifact_dir),
        }

    def run(
        self,
        *,
        messages: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        run_context = self._default_context()
        run_context.update(context or {})

        conversation = [
            {"role": "system", "content": self.config.agent.system_prompt},
            *normalize_messages(messages),
        ]
        tool_logs: list[ToolCallLog] = []
        artifact_paths: list[str] = []
        usage: dict[str, Any] = {}

        for _turn in range(self.config.agent.max_turns):
            try:
                response = self.provider.complete(
                    messages=conversation,
                    tools=self.tools.provider_tools(),
                    temperature=self.config.agent.temperature,
                )
            except Exception as exc:
                return RunResult(
                    status="error",
                    messages=conversation,
                    tool_calls=tool_logs,
                    artifact_paths=artifact_paths,
                    usage=usage,
                    errors=[str(exc)],
                )

            for key, value in response.usage.items():
                existing = usage.get(key)
                if isinstance(existing, (int, float)) and isinstance(value, (int, float)):
                    usage[key] = existing + value
                else:
                    usage[key] = value
            conversation.append(response.message)

            if not response.tool_calls:
                final_text = str(response.message.get("content") or "")
                return RunResult(
                    status="ok",
                    messages=conversation,
                    final_text=final_text,
                    tool_calls=tool_logs,
                    artifact_paths=artifact_paths,
                    usage=usage,
                )

            for call in response.tool_calls:
                log = ToolCallLog(name=call.name, arguments=call.arguments)
                try:
                    result = self.tools.run(call.name, call.arguments, run_context)
                    log.result = result
                    if isinstance(result, dict) and "artifact_paths" in result:
                        artifact_paths.extend(
                            str(artifact_path)
                            for artifact_path in result["artifact_paths"]
                            if isinstance(artifact_path, str)
                        )
                    try:
                        tool_content = json.dumps(result, ensure_ascii=False)
                    except (TypeError, ValueError):
                        tool_content = str(result)
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": tool_content,
                        }
                    )
                except Exception as exc:
                    log.error = str(exc)
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": f"ERROR: {exc}",
                        }
                    )
                tool_logs.append(log)

        return RunResult(
            status="error",
            messages=conversation,
            tool_calls=tool_logs,
            artifact_paths=artifact_paths,
            usage=usage,
            errors=["max turns reached"],
        )
