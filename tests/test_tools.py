import json
import shutil
from pathlib import Path

import pytest

from agentic_core.schemas import ToolConfig
from agentic_core.tools import build_default_registry
from agentic_core.tools.registry import ToolDisabledError, ToolInvalidArgumentsError, ToolRegistry


def test_tool_registry_runs_enabled_tool():
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
        handler=lambda args, context: {"text": args["text"]},
    )

    assert registry.run("echo", {"text": "hi"}, {}) == {"text": "hi"}


def test_tool_registry_rejects_disabled_tool():
    registry = ToolRegistry({"echo": ToolConfig(enabled=False)})
    registry.register(
        name="echo",
        description="Echo text",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args, context: {},
    )

    with pytest.raises(ToolDisabledError, match="tool disabled: echo"):
        registry.run("echo", {}, {})


def test_tool_registry_rejects_unknown_arguments_when_schema_forbids_them():
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
        handler=lambda args, context: {"text": args["text"]},
    )

    with pytest.raises(ToolInvalidArgumentsError, match="unexpected argument"):
        registry.run("echo", {"text": "hi", "path": "/tmp/secret.json"}, {})


def test_tool_registry_rejects_missing_required_arguments():
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
        handler=lambda args, context: {"text": args["text"]},
    )

    with pytest.raises(ToolInvalidArgumentsError, match="missing required argument"):
        registry.run("echo", {}, {})


def test_read_signals_reads_configured_file():
    registry = build_default_registry({"read_signals": ToolConfig(enabled=True)})
    allowed_path = Path.cwd() / "data" / "signals" / "latest.json"
    allowed_path.parent.mkdir(parents=True, exist_ok=True)
    allowed_path.write_text(json.dumps({"signals": [{"title": "A"}]}), encoding="utf-8")
    try:
        result = registry.run("read_signals", {}, {"signals_path": str(allowed_path)})
        assert result["signals"][0]["title"] == "A"
    finally:
        if allowed_path.exists():
            allowed_path.unlink()


def test_read_signals_rejects_outside_path():
    registry = build_default_registry({"read_signals": ToolConfig(enabled=True)})

    with pytest.raises(ValueError, match="path outside repository"):
        registry.run("read_signals", {}, {"signals_path": "/tmp/outside-signals.json"})


def test_default_registry_exposes_l3_runtime_tools():
    registry = build_default_registry(
        {
            "read_refresh_status": ToolConfig(enabled=True),
            "read_latest_run": ToolConfig(enabled=True),
            "run_refresh_pipeline": ToolConfig(enabled=True),
        }
    )

    tool_names = {tool["function"]["name"] for tool in registry.provider_tools()}

    assert "read_refresh_status" in tool_names
    assert "read_latest_run" in tool_names
    assert "run_refresh_pipeline" in tool_names


def test_read_artifact_tools_do_not_expose_path_arguments_to_provider():
    registry = build_default_registry(
        {
            "read_signals": ToolConfig(enabled=True),
            "read_canonical_items": ToolConfig(enabled=True),
        }
    )

    tools = {tool["function"]["name"]: tool for tool in registry.provider_tools()}

    assert tools["read_signals"]["function"]["parameters"]["properties"] == {}
    assert tools["read_canonical_items"]["function"]["parameters"]["properties"] == {}


def test_read_artifact_tools_reject_model_supplied_path_arguments():
    registry = build_default_registry(
        {
            "read_signals": ToolConfig(enabled=True),
            "read_canonical_items": ToolConfig(enabled=True),
        }
    )

    with pytest.raises(ToolInvalidArgumentsError, match="unexpected argument"):
        registry.run("read_signals", {"path": "/tmp/outside-signals.json"}, {})


def test_write_agentic_artifact_writes_json_and_markdown():
    registry = build_default_registry({"write_agentic_artifact": ToolConfig(enabled=True)})
    allowed_dir = Path.cwd() / "data" / "agentic" / "test-output"
    if allowed_dir.exists():
        shutil.rmtree(allowed_dir)

    try:
        result = registry.run(
            "write_agentic_artifact",
            {"final_text": "hello", "data": {"answer": 42}},
            {"artifact_dir": str(allowed_dir)},
        )

        assert (allowed_dir / "latest.json").exists()
        assert (allowed_dir / "latest.md").read_text(encoding="utf-8") == "hello\n"
        assert sorted(result["artifact_paths"]) == sorted(
            [str(allowed_dir / "latest.json"), str(allowed_dir / "latest.md")]
        )
    finally:
        if allowed_dir.exists():
            shutil.rmtree(allowed_dir)


def test_write_agentic_artifact_rejects_outside_artifact_dir():
    registry = build_default_registry({"write_agentic_artifact": ToolConfig(enabled=True)})

    with pytest.raises(ValueError, match="artifact_dir outside data/agentic"):
        registry.run(
            "write_agentic_artifact",
            {"final_text": "hello", "data": {"answer": 42}},
            {"artifact_dir": "/tmp/outside-agentic"},
        )
