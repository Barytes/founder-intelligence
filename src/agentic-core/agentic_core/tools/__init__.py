from agentic_core.schemas import ToolConfig
from agentic_core.tools.founder_tools import (
    read_canonical_items,
    read_signals,
    write_agentic_artifact,
)
from agentic_core.tools.pipeline_tools import run_refresh_pipeline
from agentic_core.tools.registry import ToolRegistry
from agentic_core.tools.runtime_tools import read_latest_run, read_refresh_status


NO_ARG_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def build_default_registry(config: dict[str, ToolConfig]) -> ToolRegistry:
    registry = ToolRegistry(config)
    registry.register(
        name="read_signals",
        description="Read Founder Intelligence signals JSON from the local project.",
        parameters=NO_ARG_SCHEMA,
        handler=read_signals,
    )
    registry.register(
        name="read_canonical_items",
        description="Read canonical items JSON from the local project.",
        parameters=NO_ARG_SCHEMA,
        handler=read_canonical_items,
    )
    registry.register(
        name="read_refresh_status",
        description="Read the latest Founder Intelligence refresh status.",
        parameters=NO_ARG_SCHEMA,
        handler=read_refresh_status,
    )
    registry.register(
        name="read_latest_run",
        description="Read the latest Founder Intelligence store run record.",
        parameters=NO_ARG_SCHEMA,
        handler=read_latest_run,
    )
    registry.register(
        name="run_refresh_pipeline",
        description="Run one controlled RSS-only Founder Intelligence refresh through the Python-native pipeline runner.",
        parameters={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "additionalProperties": False,
        },
        handler=run_refresh_pipeline,
    )
    registry.register(
        name="write_agentic_artifact",
        description="Write Agentic Core final JSON and Markdown artifacts locally.",
        parameters={
            "type": "object",
            "properties": {
                "final_text": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["final_text", "data"],
            "additionalProperties": False,
        },
        handler=write_agentic_artifact,
    )
    return registry
