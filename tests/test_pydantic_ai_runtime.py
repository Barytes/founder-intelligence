from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, ConfigDict
from pydantic_ai import ModelResponse, RequestUsage, TextPart, ToolCallPart, models
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel

from agentic_core.core import AgenticCore
from agentic_core.runtime.pydantic_ai_runtime import (
    PydanticAIRuntime,
    RuntimeBudget,
    _trace_events,
    build_openai_compatible_model,
)
from agentic_core.schemas import (
    AgentConfig,
    AgenticConfig,
    PathConfig,
    ProviderConfig,
    RunResult,
    ToolConfig,
)
from agentic_core.tools.registry import ToolRegistry


models.ALLOW_MODEL_REQUESTS = False


class TypedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answer: str


def make_config(max_turns: int = 4) -> AgenticConfig:
    return AgenticConfig(
        provider=ProviderConfig(
            type="openai_compatible",
            api_key_env="TEST_KEY",
            api_key="secret",
            base_url="https://example.test/v1",
            model="test-model",
        ),
        agent=AgentConfig(
            system_prompt="System prompt",
            max_turns=max_turns,
            temperature=0.2,
            timeout_seconds=30,
        ),
        tools={"echo": ToolConfig(enabled=True)},
        paths=PathConfig(),
    )


def echo_registry(handler=None) -> ToolRegistry:
    registry = ToolRegistry({"echo": ToolConfig(enabled=True)})
    registry.register(
        name="echo",
        description="Echo text",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=handler or (lambda args, context: {"echo": args["text"]}),
    )
    return registry


def test_openai_compatible_model_is_confined_to_runtime_factory():
    model = build_openai_compatible_model(
        make_config().provider, timeout_seconds=12.5
    )

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "test-model"
    assert model.client.timeout.connect == 12.5
    assert model.client.timeout.read == 12.5


def test_openai_compatible_model_runs_through_configured_endpoint_without_network():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = build_openai_compatible_model(
        make_config().provider,
        http_client=client,
    )
    runtime = PydanticAIRuntime(
        config=make_config(), tools=ToolRegistry(), model=model
    )

    with models.override_allow_model_requests(True):
        result = runtime.run(
            messages=[{"role": "user", "content": "hello"}]
        )

    assert result.status == "ok"
    assert result.final_text == "hello"
    assert result.usage["total_tokens"] == 5
    asyncio.run(client.aclose())


def test_deepseek_v4_requests_disable_thinking_mode_without_network():
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.update(payload)
        output_tool = payload["tools"][0]["function"]["name"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-deepseek-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": output_tool,
                                        "arguments": json.dumps(
                                            {"answer": "fixture"}
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    config = make_config().model_copy(
        update={
            "provider": make_config().provider.model_copy(
                update={
                    "base_url": "https://api.deepseek.com/",
                    "model": "deepseek-v4-flash",
                }
            )
        }
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = build_openai_compatible_model(config.provider, http_client=client)
    runtime = PydanticAIRuntime(config=config, tools=ToolRegistry(), model=model)

    with models.override_allow_model_requests(True):
        result = runtime.run_typed(
            messages=[{"role": "user", "content": "compile"}],
            output_type=TypedAnswer,
        )

    assert result.status == "ok"
    assert result.output == TypedAnswer(answer="fixture")
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["temperature"] == 0.2
    asyncio.run(client.aclose())


def test_non_deepseek_compatible_requests_do_not_receive_thinking_extension():
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    config = make_config()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = build_openai_compatible_model(config.provider, http_client=client)
    runtime = PydanticAIRuntime(config=config, tools=ToolRegistry(), model=model)

    with models.override_allow_model_requests(True):
        result = runtime.run(messages=[{"role": "user", "content": "hello"}])

    assert result.status == "ok"
    assert "thinking" not in captured
    asyncio.run(client.aclose())


def test_test_model_produces_typed_output_without_network():
    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=ToolRegistry(),
        model=TestModel(custom_output_args={"answer": "fixture"}),
    )

    result = runtime.run_typed(
        messages=[{"role": "user", "content": "answer"}],
        output_type=TypedAnswer,
    )

    assert result.status == "ok"
    assert result.output == TypedAnswer(answer="fixture")
    assert result.usage["requests"] == 1


def test_typed_dependencies_and_registry_tool_adapter_preserve_context_and_trace():
    seen: dict[str, Any] = {}

    def handler(args, context):
        seen.update(context)
        return {"echo": args["text"], "artifact_paths": ["data/agentic/a.json"]}

    def recorded_model(messages, info):
        if len(messages) == 1:
            assert [tool.name for tool in info.function_tools] == ["echo"]
            return ModelResponse(
                parts=[ToolCallPart("echo", {"text": "hi"}, tool_call_id="call-1")],
                usage=RequestUsage(input_tokens=2, output_tokens=3),
            )
        return ModelResponse(
            parts=[TextPart("final answer")],
            usage=RequestUsage(input_tokens=4, output_tokens=5),
        )

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=echo_registry(handler),
        model=FunctionModel(recorded_model),
    )
    result = runtime.run(
        messages=[{"role": "user", "content": "say hi"}],
        context={"profile_id": "profile-1"},
    )

    assert result.status == "ok"
    assert result.final_text == "final answer"
    assert seen == {"profile_id": "profile-1"}
    assert result.tool_calls[0].arguments == {"text": "hi"}
    assert result.tool_calls[0].result == {
        "echo": "hi",
        "artifact_paths": ["data/agentic/a.json"],
    }
    assert result.artifact_paths == ["data/agentic/a.json"]
    assert result.usage["total_tokens"] == 14

    typed = runtime.run_typed(
        messages=[{"role": "user", "content": "plain"}],
        output_type=str,
    )
    assert typed.status == "ok"
    assert {event.kind for event in typed.trace_events} >= {
        "user-prompt",
        "tool-call",
        "tool-return",
        "text",
    }


def test_invalid_structured_output_retries_then_succeeds():
    calls = 0

    def invalid_then_valid(_messages, info):
        nonlocal calls
        calls += 1
        output_tool = info.output_tools[0]
        args = {"answer": 123} if calls == 1 else {"answer": "valid"}
        return ModelResponse(parts=[ToolCallPart(output_tool.name, args)])

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=ToolRegistry(),
        model=FunctionModel(invalid_then_valid),
        retries=1,
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "answer"}],
        output_type=TypedAnswer,
    )

    assert result.status == "ok"
    assert result.output == TypedAnswer(answer="valid")
    assert calls == 2
    assert "retry-prompt" in [event.kind for event in result.trace_events]


def test_invalid_structured_output_exhaustion_is_structured_error():
    def always_invalid(_messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"answer": 123})]
        )

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=ToolRegistry(),
        model=FunctionModel(always_invalid),
        retries=1,
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "answer"}],
        output_type=TypedAnswer,
    )

    assert result.status == "error"
    assert result.output is None
    assert result.errors and result.errors[0].startswith("UnexpectedModelBehavior:")
    assert "retry-prompt" in [event.kind for event in result.trace_events]


def test_request_budget_is_enforced_locally():
    def keep_calling(_messages, _info):
        return ModelResponse(parts=[ToolCallPart("echo", {"text": "again"})])

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=echo_registry(),
        model=FunctionModel(keep_calling),
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "loop"}],
        output_type=str,
        budget=RuntimeBudget(request_limit=1),
    )

    assert result.status == "error"
    assert "UsageLimitExceeded" in result.errors[0]
    assert "request_limit" in result.errors[0]
    assert result.usage["requests"] == 1


def test_tool_call_budget_is_enforced_locally():
    def two_calls(_messages, _info):
        return ModelResponse(
            parts=[
                ToolCallPart("echo", {"text": "one"}),
                ToolCallPart("echo", {"text": "two"}),
            ]
        )

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=echo_registry(),
        model=FunctionModel(two_calls),
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "twice"}],
        output_type=str,
        budget=RuntimeBudget(request_limit=2, tool_calls_limit=1),
    )

    assert result.status == "error"
    assert "UsageLimitExceeded" in result.errors[0]
    assert "tool_calls_limit" in result.errors[0]


def test_token_budget_is_enforced_locally():
    def expensive(_messages, _info):
        return ModelResponse(
            parts=[TextPart("done")],
            usage=RequestUsage(input_tokens=6, output_tokens=5),
        )

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=ToolRegistry(),
        model=FunctionModel(expensive),
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "spend"}],
        output_type=str,
        budget=RuntimeBudget(request_limit=2, total_tokens_limit=10),
    )

    assert result.status == "error"
    assert "UsageLimitExceeded" in result.errors[0]
    assert "total_tokens_limit" in result.errors[0]
    assert result.usage["total_tokens"] == 11


def test_tool_registry_permission_validation_cannot_be_bypassed():
    executed = False

    def handler(_args, _context):
        nonlocal executed
        executed = True
        return "bad"

    calls = 0

    def extra_argument(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart("echo", {"text": "hi", "unexpected": True})]
            )
        return ModelResponse(parts=[TextPart("stopped")])

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=echo_registry(handler),
        model=FunctionModel(extra_argument),
        retries=0,
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "unsafe"}],
        output_type=str,
    )

    assert result.status == "ok"
    assert result.output == "stopped"
    assert executed is False
    assert result.tool_calls[0].error == "unexpected argument: unexpected"
    assert "tool-return" in [event.kind for event in result.trace_events]


def test_model_and_tool_calls_export_opentelemetry_spans_in_memory():
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    def traced_exchange(messages, _info):
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("echo", {"text": "traced"})])
        return ModelResponse(parts=[TextPart("traced")])

    runtime = PydanticAIRuntime(
        config=make_config(),
        tools=echo_registry(),
        model=FunctionModel(traced_exchange),
        tracer_provider=tracer_provider,
    )
    result = runtime.run_typed(
        messages=[{"role": "user", "content": "trace"}],
        output_type=str,
    )

    tracer_provider.force_flush()
    spans = exporter.get_finished_spans()
    assert result.status == "ok"
    assert len(spans) >= 3
    assert any(span.parent is not None for span in spans)
    assert any("test-function" in span.name or "agent" in span.name for span in spans)


def test_pydantic_ai_imports_do_not_leak_outside_runtime_adapter():
    source_root = Path(__file__).resolve().parents[1] / "src" / "agentic-core" / "agentic_core"
    leaked = []
    for path in source_root.rglob("*.py"):
        if "runtime" in path.relative_to(source_root).parts:
            continue
        imports_framework = any(
            line.startswith(("from pydantic_ai", "import pydantic_ai"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if imports_framework:
            leaked.append(path.relative_to(source_root).as_posix())

    assert leaked == []


def test_trace_projection_never_records_private_reasoning_content():
    messages = [
        SimpleNamespace(
            parts=[SimpleNamespace(part_kind="thinking", content="private reasoning")]
        )
    ]

    events = _trace_events(messages)

    assert events[0].kind == "thinking"
    assert events[0].content == "[redacted]"


def test_agentic_core_facade_can_delegate_without_changing_return_contract():
    class Runtime:
        def run(self, *, messages, context=None):
            return RunResult(
                status="ok",
                messages=messages,
                final_text=f"runtime:{context['value']}",
            )

    core = AgenticCore(
        config=make_config(),
        tools=ToolRegistry(),
        runtime=Runtime(),
    )
    result = core.run(
        messages=[{"role": "user", "content": "hi"}],
        context={"value": "ok"},
    )

    assert isinstance(result, RunResult)
    assert result.final_text == "runtime:ok"


def test_runtime_closes_only_the_openai_client_it_owns():
    runtime = PydanticAIRuntime(config=make_config(), tools=ToolRegistry())
    assert runtime._owned_model is not None
    assert runtime._owned_model.client.is_closed() is False

    asyncio.run(runtime.aclose())

    assert runtime._owned_model.client.is_closed() is True


def test_sync_runtime_close_is_safe_when_caller_event_loop_is_running():
    runtime = PydanticAIRuntime(config=make_config(), tools=ToolRegistry())

    async def close_from_async_route():
        runtime.close()

    asyncio.run(close_from_async_route())

    assert runtime._owned_model.client.is_closed() is True
