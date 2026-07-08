from pathlib import Path

from agentic_core.config import load_agentic_config
from agentic_core.schemas import AgenticConfig


class AgenticCore:
    """Callable Agentic Core component."""

    def __init__(self, config: AgenticConfig):
        self.config = config

    @classmethod
    def from_config(cls, config_path: str | Path) -> "AgenticCore":
        return cls(load_agentic_config(config_path))
