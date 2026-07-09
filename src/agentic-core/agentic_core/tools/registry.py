from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentic_core.schemas import ToolConfig


class ToolDisabledError(RuntimeError):
    pass


class ToolNotFoundError(RuntimeError):
    pass


class ToolInvalidArgumentsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], dict[str, Any]], Any]

    def as_provider_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _validate_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> None:
    parameters = tool.parameters or {}
    properties = parameters.get("properties") or {}
    required = parameters.get("required") or []

    if parameters.get("type") == "object" and not isinstance(arguments, dict):
        raise ToolInvalidArgumentsError("tool arguments must be an object")

    if parameters.get("additionalProperties") is False:
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise ToolInvalidArgumentsError(f"unexpected argument: {unexpected[0]}")

    for name in required:
        if name not in arguments:
            raise ToolInvalidArgumentsError(f"missing required argument: {name}")


class ToolRegistry:
    def __init__(self, config: dict[str, ToolConfig] | None = None):
        self.config = config or {}
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[[dict[str, Any], dict[str, Any]], Any],
    ) -> None:
        self._tools[name] = ToolDefinition(name, description, parameters, handler)

    def enabled_tools(self) -> list[ToolDefinition]:
        result: list[ToolDefinition] = []
        for name, tool in self._tools.items():
            if self.config.get(name, ToolConfig(enabled=True)).enabled:
                result.append(tool)
        return result

    def provider_tools(self) -> list[dict[str, Any]]:
        return [tool.as_provider_tool() for tool in self.enabled_tools()]

    def run(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"unknown tool: {name}")
        if not self.config.get(name, ToolConfig(enabled=True)).enabled:
            raise ToolDisabledError(f"tool disabled: {name}")
        _validate_arguments(tool, arguments)
        return tool.handler(arguments, context)
