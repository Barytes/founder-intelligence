from agentic_core.schemas import ToolConfig
from agentic_core.tools.founder_tools import (
    read_canonical_items,
    read_signals,
    write_agentic_artifact,
)
from agentic_core.tools.registry import ToolRegistry


PATH_ARG_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "additionalProperties": False,
}


def build_default_registry(config: dict[str, ToolConfig]) -> ToolRegistry:
    registry = ToolRegistry(config)
    registry.register(
        name="read_signals",
        description="Read Founder Intelligence signals JSON from the local project.",
        parameters=PATH_ARG_SCHEMA,
        handler=read_signals,
    )
    registry.register(
        name="read_canonical_items",
        description="Read canonical items JSON from the local project.",
        parameters=PATH_ARG_SCHEMA,
        handler=read_canonical_items,
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
