from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["openai_compatible"]
    api_key_env: str
    base_url_env: str | None = None
    default_base_url: str = "https://api.openai.com/v1"
    model: str
    api_key: str | None = Field(default=None, exclude=True)
    base_url: str | None = None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "api_key_env": self.api_key_env,
            "api_key_configured": bool(self.api_key),
            "base_url_env": self.base_url_env,
            "base_url": self.base_url or self.default_base_url,
            "model": self.model,
        }


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str
    max_turns: int = Field(default=8, ge=1, le=32)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=60, gt=0)


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class PathConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: Path = Path("data/signals/latest.json")
    canonical_items: Path = Path("data/canonical-items/latest.json")
    artifact_dir: Path = Path("data/agentic")


class AgenticConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderConfig
    agent: AgentConfig
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    paths: PathConfig = Field(default_factory=PathConfig)


class ToolCallLog(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: Any | None = None
    error: str | None = None


class RunResult(BaseModel):
    status: Literal["ok", "error"]
    messages: list[dict[str, Any]]
    final_text: str = ""
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
