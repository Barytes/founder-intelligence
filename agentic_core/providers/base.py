from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ProviderResponse:
    message: dict[str, Any]
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float,
    ) -> ProviderResponse:
        ...
