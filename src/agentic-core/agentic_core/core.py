from pathlib import Path
from typing import Any

from agentic_core.config import load_agentic_config
from agentic_core.runtime.base import AgentRuntime
from agentic_core.runtime.pydantic_ai_runtime import PydanticAIRuntime
from agentic_core.schemas import AgenticConfig, RunResult
from agentic_core.tools import build_default_registry
from agentic_core.tools.registry import ToolRegistry


class AgenticCore:
    """Stable facade over the single PydanticAI Agent runtime."""

    def __init__(
        self,
        config: AgenticConfig,
        tools: ToolRegistry | None = None,
        runtime: AgentRuntime | None = None,
    ):
        self.config = config
        self.tools = tools or build_default_registry(config.tools)
        self.runtime = runtime or PydanticAIRuntime(config=config, tools=self.tools)

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
        return self.runtime.run(messages=messages, context=run_context)

    def close(self) -> None:
        close = getattr(self.runtime, "close", None)
        if callable(close):
            close()
