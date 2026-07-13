import json

from pydantic_ai import ModelResponse, RequestUsage, TextPart, ToolCallPart, models
from pydantic_ai.models.function import FunctionModel

from agentic_core.core import AgenticCore
from agentic_core.runtime.pydantic_ai_runtime import PydanticAIRuntime
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


def make_registry(name: str = "echo", handler=None) -> ToolRegistry:
    registry = ToolRegistry({name: ToolConfig(enabled=True)})
    properties = {"text": {"type": "string"}} if name == "echo" else {}
    registry.register(
        name=name,
        description=f"{name} tool",
        parameters={
            "type": "object",
            "properties": properties,
            "required": ["text"] if name == "echo" else [],
            "additionalProperties": False,
        },
        handler=handler
        or (
            (lambda args, context: {"echo": args["text"]})
            if name == "echo"
            else (lambda _args, _context: {})
        ),
    )
    return registry


def make_core(config, registry, model) -> AgenticCore:
    runtime = PydanticAIRuntime(config=config, tools=registry, model=model)
    return AgenticCore(config=config, tools=registry, runtime=runtime)


def test_core_defaults_to_pydantic_ai_runtime():
    core = AgenticCore(config=make_config(), tools=ToolRegistry())

    assert isinstance(core.runtime, PydanticAIRuntime)
    assert not hasattr(core, "provider")

    core.close()


def test_core_runs_tool_loop_to_final_answer_and_preserves_messages():
    def recorded_model(messages, _info):
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("echo", {"text": "hi"}, tool_call_id="call-1")],
                usage=RequestUsage(input_tokens=2, output_tokens=3),
            )
        return ModelResponse(
            parts=[TextPart("final answer")],
            usage=RequestUsage(input_tokens=4, output_tokens=5),
        )

    config = make_config()
    registry = make_registry()
    core = make_core(config, registry, FunctionModel(recorded_model))

    result = core.run(messages=[{"role": "user", "content": "say hi"}])

    assert result.status == "ok"
    assert result.final_text == "final answer"
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].arguments == {"text": "hi"}
    assert result.tool_calls[0].result == {"echo": "hi"}
    assert result.usage["total_tokens"] == 14
    tool_messages = [message for message in result.messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"]) == {"echo": "hi"}


def test_core_groups_parallel_tool_calls_in_one_assistant_message():
    def recorded_model(messages, _info):
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart("echo", {"text": "one"}, tool_call_id="call-1"),
                    ToolCallPart("echo", {"text": "two"}, tool_call_id="call-2"),
                ]
            )
        return ModelResponse(parts=[TextPart("done")])

    core = make_core(
        make_config(), make_registry(), FunctionModel(recorded_model)
    )

    result = core.run(messages=[{"role": "user", "content": "twice"}])

    assistant_calls = [
        message for message in result.messages if message.get("tool_calls")
    ]
    assert len(assistant_calls) == 1
    assert [
        call["function"]["name"] for call in assistant_calls[0]["tool_calls"]
    ] == ["echo", "echo"]


def test_core_enforces_max_turns_through_pydantic_usage_limits():
    model = FunctionModel(
        lambda _messages, _info: ModelResponse(
            parts=[ToolCallPart("echo", {"text": "again"})]
        )
    )
    config = make_config(max_turns=1)
    core = make_core(config, make_registry(), model)

    result = core.run(messages=[{"role": "user", "content": "loop"}])

    assert result.status == "error"
    assert result.errors == ["max turns reached"]


def test_core_aggregates_artifact_paths_from_tool_results():
    registry = make_registry(
        "write",
        lambda _args, _context: {
            "artifact_paths": ["data/agentic/latest.json"]
        },
    )

    def recorded_model(messages, _info):
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("write", {})])
        return ModelResponse(parts=[TextPart("written")])

    core = make_core(make_config(), registry, FunctionModel(recorded_model))

    result = core.run(messages=[{"role": "user", "content": "write"}])

    assert result.status == "ok"
    assert result.artifact_paths == ["data/agentic/latest.json"]


def test_core_returns_structured_error_when_model_fails():
    def failing_model(_messages, _info):
        raise RuntimeError("provider down")

    core = make_core(
        make_config(), ToolRegistry(), FunctionModel(failing_model)
    )

    result = core.run(messages=[{"role": "user", "content": "oops"}])

    assert result.status == "error"
    assert result.errors == ["RuntimeError: provider down"]
    assert result.tool_calls == []


def test_core_records_tool_error_and_returns_it_to_model():
    registry = make_registry("broken", lambda _args, _context: 1 / 0)

    def recorded_model(messages, _info):
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("broken", {})])
        return ModelResponse(parts=[TextPart("recovered")])

    core = make_core(make_config(), registry, FunctionModel(recorded_model))

    result = core.run(messages=[{"role": "user", "content": "bad"}])

    assert result.status == "ok"
    assert result.final_text == "recovered"
    assert result.tool_calls[0].error == "division by zero"
    tool_messages = [message for message in result.messages if message["role"] == "tool"]
    assert tool_messages[0]["content"].startswith("ERROR:")


def test_core_merges_default_and_explicit_context_before_runtime():
    class Runtime:
        def __init__(self):
            self.context = None

        def run(self, *, messages, context=None):
            self.context = context
            return RunResult(status="ok", messages=messages, final_text="ok")

    runtime = Runtime()
    core = AgenticCore(config=make_config(), tools=ToolRegistry(), runtime=runtime)

    result = core.run(
        messages=[{"role": "user", "content": "context"}],
        context={"profile_id": "profile-1"},
    )

    assert result.status == "ok"
    assert runtime.context == {
        "signals_path": "data/signals/latest.json",
        "canonical_items_path": "data/canonical-items/latest.json",
        "artifact_dir": "data/agentic",
        "profile_id": "profile-1",
    }
