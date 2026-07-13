from typing import Any, Protocol

from agentic_core.schemas import RunResult


class AgentRuntime(Protocol):
    """Framework-independent compatibility boundary used by AgenticCore."""

    def run(
        self,
        *,
        messages: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        ...
