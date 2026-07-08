import json

from agentic_core.core import AgenticCore
from agentic_core.providers.base import ProviderResponse, ProviderToolCall
from agentic_core.schemas import AgenticConfig, AgentConfig, PathConfig, ProviderConfig, ToolConfig
from agentic_core.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, *, messages, tools, temperature):
        self.calls += 1
        if self.calls == 1:
            return ProviderResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": '{"text":"hi"}'},
                        }
                    ],
                },
                usage={"total_tokens": 5},
                tool_calls=[ProviderToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
            )
        return ProviderResponse(
            message={"role": "assistant", "content": "final answer"},
            usage={"total_tokens": 7},
        )


def make_config(max_turns=4):
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


def test_core_runs_tool_loop_to_final_answer():
    provider = FakeProvider()
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
        handler=lambda args, context: {"echo": args["text"]},
    )
    core = AgenticCore(config=make_config(), provider=provider, tools=registry)

    result = core.run(messages=[{"role": "user", "content": "say hi"}], context={})

    assert result.status == "ok"
    assert result.final_text == "final answer"
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].result == {"echo": "hi"}
    assert result.tool_calls[0].arguments == {"text": "hi"}
    assert result.usage == {"total_tokens": 12}

    tool_messages = [m for m in result.messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"]) == {"echo": "hi"}


def test_core_returns_error_when_max_turns_reached():
    class LoopingProvider:
        def complete(self, *, messages, tools, temperature):
            return ProviderResponse(
                message={"role": "assistant", "content": "", "tool_calls": []},
                tool_calls=[ProviderToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
            )

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
        handler=lambda args, context: {"echo": args["text"]},
    )
    core = AgenticCore(config=make_config(max_turns=1), provider=LoopingProvider(), tools=registry)

    result = core.run(messages=[{"role": "user", "content": "loop"}], context={})

    assert result.status == "error"
    assert result.errors == ["max turns reached"]


def test_core_serializes_tool_result_as_json_for_tool_messages():
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
        handler=lambda args, context: {"echo": args["text"]},
    )

    class Provider:
        def complete(self, *, messages, tools, temperature):
            return ProviderResponse(
                message={"role": "assistant", "content": "", "tool_calls": []},
                tool_calls=[ProviderToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
            )

    core = AgenticCore(config=make_config(max_turns=1), provider=Provider(), tools=registry)
    result = core.run(messages=[{"role": "user", "content": "say hi"}], context={})

    assert result.status == "error"
    assert result.errors == ["max turns reached"]
    tool_messages = [m for m in result.messages if m.get("role") == "tool"]
    assert tool_messages and tool_messages[0]["content"] == json.dumps({"echo": "hi"}, ensure_ascii=False)


def test_core_aggregates_artifact_paths_from_tool_results():
    class ArtifactProvider:
        def complete(self, *, messages, tools, temperature):
            return ProviderResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "write", "arguments": "{}"},
                        }
                    ],
                },
                tool_calls=[ProviderToolCall(id="call_1", name="write", arguments={})],
            )

    registry = ToolRegistry({"write": ToolConfig(enabled=True)})
    registry.register(
        name="write",
        description="Write artifact",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=lambda args, context: {"artifact_paths": ["data/agentic/latest.json"]},
    )
    core = AgenticCore(
        config=make_config(max_turns=1),
        provider=ArtifactProvider(),
        tools=registry,
    )
    result = core.run(messages=[{"role": "user", "content": "write"}], context={})

    assert result.artifact_paths == ["data/agentic/latest.json"]


def test_core_accumulates_numeric_usage_over_turns():
    class MultiUsageProvider:
        def __init__(self):
            self.calls = 0

        def complete(self, *, messages, tools, temperature):
            self.calls += 1
            if self.calls == 1:
                return ProviderResponse(
                    message={
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "echo", "arguments": '{"text":"hello"}'},
                            }
                        ],
                    },
                    usage={"total_tokens": 5, "mode": "chat"},
                    tool_calls=[ProviderToolCall(id="call_1", name="echo", arguments={"text": "hello"})],
                )
            return ProviderResponse(
                message={"role": "assistant", "content": "done"},
                usage={"total_tokens": 7, "mode": "final"},
            )

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
        handler=lambda args, context: {"echo": args["text"]},
    )
    core = AgenticCore(config=make_config(), provider=MultiUsageProvider(), tools=registry)

    result = core.run(messages=[{"role": "user", "content": "sum usage"}], context={})

    assert result.status == "ok"
    assert result.usage == {"total_tokens": 12, "mode": "final"}


def test_core_returns_error_when_provider_fails():
    class FailingProvider:
        def complete(self, *, messages, tools, temperature):
            raise RuntimeError("provider down")

    core = AgenticCore(config=make_config(), provider=FailingProvider(), tools=ToolRegistry())
    result = core.run(messages=[{"role": "user", "content": "oops"}], context={})

    assert result.status == "error"
    assert result.errors == ["provider down"]
    assert result.tool_calls == []


def test_core_records_tool_error_and_tool_error_message():
    class Provider:
        def complete(self, *, messages, tools, temperature):
            return ProviderResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "broken", "arguments": "{}"},
                        }
                    ],
                },
                tool_calls=[ProviderToolCall(id="call_1", name="broken", arguments={})],
            )

    registry = ToolRegistry({"broken": ToolConfig(enabled=True)})
    registry.register(
        name="broken",
        description="Broken tool",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args, context: 1 / 0,
    )

    core = AgenticCore(config=make_config(max_turns=1), provider=Provider(), tools=registry)
    result = core.run(messages=[{"role": "user", "content": "bad"}], context={})

    assert result.status == "error"
    assert result.errors == ["max turns reached"]
    assert result.tool_calls[0].error == "division by zero"
    tool_messages = [m for m in result.messages if m.get("role") == "tool"]
    assert tool_messages and tool_messages[0]["content"].startswith("ERROR:")
