# Agentic Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only Python Agentic Core component with configurable OpenAI-compatible LLM access, tool calling, project artifact tools, and a FastAPI web workbench.

**Architecture:** Add a Python package beside the existing Ruby pipeline. The package owns provider adapters, tool registry, config loading, and the chat/tool loop; the web workbench calls that same package and never duplicates agent logic. Existing RSS, ingestion, storage, and signal scripts remain unchanged.

**Tech Stack:** Python 3.11+, pytest, pydantic, PyYAML, python-dotenv, httpx, FastAPI, Uvicorn, vanilla HTML/CSS/JavaScript.

---

## Scope Check

This plan covers one cohesive feature: a reusable Agentic Core plus a local development workbench for that core. The web workbench is included because it is a thin client over the same component API, not a separate product runtime.

Do not modify existing files under `src/`. Do not change existing stable MVP config files except to add new example config files explicitly named for Agentic Core.

## File Map

- Create `pyproject.toml`: Python package metadata, dependencies, and pytest config.
- Create `.env.example`: documents local token environment variables.
- Create `config/agentic-core.example.yml`: non-secret Agentic Core runtime example.
- Create `agentic_core/__init__.py`: exports `AgenticCore`.
- Create `agentic_core/schemas.py`: pydantic data models for config, messages, tools, and results.
- Create `agentic_core/config.py`: loads YAML and `.env`, resolves provider config without exposing token values to UI callers.
- Create `agentic_core/messages.py`: normalizes role/content message dictionaries.
- Create `agentic_core/providers/base.py`: provider protocol and provider response models.
- Create `agentic_core/providers/openai_compatible.py`: OpenAI-compatible chat completions adapter using `httpx`.
- Create `agentic_core/providers/__init__.py`: provider factory.
- Create `agentic_core/tools/registry.py`: tool definitions, enable checks, schema validation, and execution logs.
- Create `agentic_core/tools/founder_tools.py`: local tools for reading signals/items and writing artifacts.
- Create `agentic_core/tools/__init__.py`: tool factory.
- Create `agentic_core/core.py`: core chat/tool loop.
- Create `agentic_core/run.py`: CLI entry point for smoke usage.
- Create `web_workbench/app.py`: FastAPI local server.
- Create `web_workbench/static/index.html`: local UI.
- Create `web_workbench/static/styles.css`: local UI styling.
- Create `web_workbench/static/app.js`: browser logic for chat/config/tool logs.
- Create `tests/`: unit and API tests with fake providers; no real API token required.

## Task 1: Python Project Scaffold and Example Config

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `config/agentic-core.example.yml`
- Create: `agentic_core/__init__.py`
- Create: `tests/test_imports.py`

- [ ] **Step 1: Write the package import test**

Create `tests/test_imports.py`:

```python
from agentic_core import AgenticCore


def test_agentic_core_export_exists():
    assert AgenticCore.__name__ == "AgenticCore"
```

- [ ] **Step 2: Run the import test and verify it fails**

Run:

```bash
python -m pytest tests/test_imports.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'agentic_core'
```

- [ ] **Step 3: Add Python project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "founder-intelligence-agent"
version = "0.1.0"
description = "Local Founder Intelligence Agentic Core"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "httpx>=0.27.0",
  "pydantic>=2.8.0",
  "python-dotenv>=1.0.1",
  "pyyaml>=6.0.2",
  "uvicorn>=0.30.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 4: Add environment example**

Create `.env.example`:

```env
OPENAI_API_KEY=
OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
```

- [ ] **Step 5: Add Agentic Core example YAML**

Create `config/agentic-core.example.yml`:

```yaml
provider:
  type: openai_compatible
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_COMPATIBLE_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5

agent:
  system_prompt: |
    You are the Founder Intelligence Agentic Core. Use tools when they help
    ground the analysis in local project artifacts. Preserve uncertainty.
  max_turns: 8
  temperature: 0.2
  timeout_seconds: 60

tools:
  read_signals:
    enabled: true
  read_canonical_items:
    enabled: true
  write_agentic_artifact:
    enabled: true

paths:
  signals: data/signals/latest.json
  canonical_items: data/canonical-items/latest.json
  artifact_dir: data/agentic
```

- [ ] **Step 6: Add the minimal package export**

Create `agentic_core/__init__.py`:

```python
from agentic_core.core import AgenticCore

__all__ = ["AgenticCore"]
```

Create `agentic_core/core.py`:

```python
class AgenticCore:
    """Callable Agentic Core component."""

    pass
```

- [ ] **Step 7: Run the import test and verify it passes**

Run:

```bash
python -m pytest tests/test_imports.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .env.example config/agentic-core.example.yml agentic_core/__init__.py agentic_core/core.py tests/test_imports.py
git commit -m "Add Python Agentic Core scaffold"
```

## Task 2: Schemas, Message Normalization, and Config Loading

**Files:**
- Create: `agentic_core/schemas.py`
- Create: `agentic_core/config.py`
- Create: `agentic_core/messages.py`
- Modify: `agentic_core/core.py`
- Test: `tests/test_config.py`
- Test: `tests/test_messages.py`

- [ ] **Step 1: Write config and message tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from agentic_core.config import load_agentic_config


def test_load_agentic_config_resolves_env_without_returning_secret(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.yml"
    config_path.write_text(
        """
provider:
  type: openai_compatible
  api_key_env: TEST_AGENT_KEY
  base_url_env: TEST_AGENT_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5
agent:
  system_prompt: System text
  max_turns: 4
  temperature: 0.1
  timeout_seconds: 30
tools:
  read_signals:
    enabled: true
paths:
  signals: data/signals/latest.json
  canonical_items: data/canonical-items/latest.json
  artifact_dir: data/agentic
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_AGENT_KEY", "secret-value")
    monkeypatch.setenv("TEST_AGENT_BASE_URL", "https://example.test/v1")

    config = load_agentic_config(config_path)

    assert config.provider.type == "openai_compatible"
    assert config.provider.api_key == "secret-value"
    assert config.provider.base_url == "https://example.test/v1"
    assert config.provider.safe_dict()["api_key_configured"] is True
    assert "secret-value" not in str(config.provider.safe_dict())
    assert config.agent.max_turns == 4
    assert config.tools["read_signals"].enabled is True
    assert config.paths.signals == Path("data/signals/latest.json")
```

Create `tests/test_messages.py`:

```python
import pytest

from agentic_core.messages import normalize_messages


def test_normalize_messages_accepts_role_content_dicts():
    messages = normalize_messages([{"role": "user", "content": "hello"}])

    assert messages == [{"role": "user", "content": "hello"}]


def test_normalize_messages_rejects_unknown_role():
    with pytest.raises(ValueError, match="unsupported message role"):
        normalize_messages([{"role": "admin", "content": "hello"}])


def test_normalize_messages_rejects_empty_content():
    with pytest.raises(ValueError, match="message content must not be empty"):
        normalize_messages([{"role": "user", "content": "   "}])
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_config.py tests/test_messages.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'agentic_core.config'
```

- [ ] **Step 3: Add schemas**

Create `agentic_core/schemas.py`:

```python
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
```

- [ ] **Step 4: Add config loader**

Create `agentic_core/config.py`:

```python
from pathlib import Path
import os
from typing import Any

from dotenv import load_dotenv
import yaml

from agentic_core.schemas import AgenticConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a mapping: {path}")
    return data


def load_agentic_config(config_path: str | Path) -> AgenticConfig:
    load_dotenv()
    path = Path(config_path)
    data = _read_yaml(path)
    config = AgenticConfig.model_validate(data)

    api_key = os.environ.get(config.provider.api_key_env)
    base_url = (
        os.environ.get(config.provider.base_url_env)
        if config.provider.base_url_env
        else None
    )

    return config.model_copy(
        update={
            "provider": config.provider.model_copy(
                update={
                    "api_key": api_key,
                    "base_url": base_url or config.provider.default_base_url,
                }
            )
        }
    )
```

- [ ] **Step 5: Add message normalization**

Create `agentic_core/messages.py`:

```python
from typing import Any

ALLOWED_ROLES = {"system", "user", "assistant", "tool"}


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", "")).strip()
        if role not in ALLOWED_ROLES:
            raise ValueError(f"unsupported message role at index {index}: {role}")

        content = message.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"message content must not be empty at index {index}")

        normalized.append({"role": role, "content": content.strip()})
    return normalized
```

- [ ] **Step 6: Wire `AgenticCore.from_config`**

Replace `agentic_core/core.py` with:

```python
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
```

- [ ] **Step 7: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/test_config.py tests/test_messages.py tests/test_imports.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 8: Commit**

```bash
git add agentic_core/schemas.py agentic_core/config.py agentic_core/messages.py agentic_core/core.py tests/test_config.py tests/test_messages.py
git commit -m "Add Agentic Core config schemas"
```

## Task 3: Tool Registry and Founder Intelligence Tools

**Files:**
- Create: `agentic_core/tools/__init__.py`
- Create: `agentic_core/tools/registry.py`
- Create: `agentic_core/tools/founder_tools.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write tool tests**

Create `tests/test_tools.py`:

```python
import json

import pytest

from agentic_core.schemas import ToolConfig
from agentic_core.tools import build_default_registry
from agentic_core.tools.registry import ToolDisabledError, ToolRegistry


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


def test_read_signals_reads_configured_file(tmp_path):
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps({"signals": [{"title": "A"}]}), encoding="utf-8")
    registry = build_default_registry({"read_signals": ToolConfig(enabled=True)})

    result = registry.run("read_signals", {}, {"signals_path": str(signals_path)})

    assert result["signals"][0]["title"] == "A"


def test_write_agentic_artifact_writes_json_and_markdown(tmp_path):
    registry = build_default_registry({"write_agentic_artifact": ToolConfig(enabled=True)})

    result = registry.run(
        "write_agentic_artifact",
        {"final_text": "hello", "data": {"answer": 42}},
        {"artifact_dir": str(tmp_path)},
    )

    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "latest.md").read_text(encoding="utf-8") == "hello\n"
    assert sorted(result["artifact_paths"]) == sorted(
        [str(tmp_path / "latest.json"), str(tmp_path / "latest.md")]
    )
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_tools.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'agentic_core.tools'
```

- [ ] **Step 3: Add tool registry**

Create `agentic_core/tools/registry.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentic_core.schemas import ToolConfig


class ToolDisabledError(RuntimeError):
    pass


class ToolNotFoundError(RuntimeError):
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
        return tool.handler(arguments, context)
```

- [ ] **Step 4: Add project tools**

Create `agentic_core/tools/founder_tools.py`:

```python
from pathlib import Path
import json
from typing import Any


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"artifact not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_signals(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    path = Path(arguments.get("path") or context.get("signals_path") or "data/signals/latest.json")
    return _read_json(path)


def read_canonical_items(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    path = Path(
        arguments.get("path")
        or context.get("canonical_items_path")
        or "data/canonical-items/latest.json"
    )
    return _read_json(path)


def write_agentic_artifact(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, list[str]]:
    artifact_dir = Path(context.get("artifact_dir") or "data/agentic")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    final_text = str(arguments.get("final_text") or "")
    data = arguments.get("data") or {}

    json_path = artifact_dir / "latest.json"
    markdown_path = artifact_dir / "latest.md"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    markdown_path.write_text(final_text.rstrip() + "\n", encoding="utf-8")

    return {"artifact_paths": [str(json_path), str(markdown_path)]}
```

- [ ] **Step 5: Add default registry factory**

Create `agentic_core/tools/__init__.py`:

```python
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
```

- [ ] **Step 6: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/test_tools.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 7: Commit**

```bash
git add agentic_core/tools tests/test_tools.py
git commit -m "Add Agentic Core tool registry"
```

## Task 4: Provider Adapter With Fakeable OpenAI-Compatible Client

**Files:**
- Create: `agentic_core/providers/__init__.py`
- Create: `agentic_core/providers/base.py`
- Create: `agentic_core/providers/openai_compatible.py`
- Test: `tests/test_provider.py`

- [ ] **Step 1: Write provider tests**

Create `tests/test_provider.py`:

```python
import httpx
import pytest

from agentic_core.providers import build_provider
from agentic_core.providers.openai_compatible import OpenAICompatibleProvider
from agentic_core.schemas import ProviderConfig


def test_provider_factory_builds_openai_compatible_provider():
    provider = build_provider(
        ProviderConfig(
            type="openai_compatible",
            api_key_env="TEST_KEY",
            api_key="secret",
            base_url="https://example.test/v1",
            model="test-model",
        )
    )

    assert isinstance(provider, OpenAICompatibleProvider)


def test_openai_compatible_requires_api_key():
    config = ProviderConfig(
        type="openai_compatible",
        api_key_env="TEST_KEY",
        api_key=None,
        base_url="https://example.test/v1",
        model="test-model",
    )

    with pytest.raises(ValueError, match="missing API key"):
        OpenAICompatibleProvider(config)


def test_openai_compatible_parses_final_text_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "hello"}}
                ],
                "usage": {"total_tokens": 7},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        ProviderConfig(
            type="openai_compatible",
            api_key_env="TEST_KEY",
            api_key="secret",
            base_url="https://example.test/v1",
            model="test-model",
        ),
        client=client,
    )

    response = provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.1)

    assert response.message == {"role": "assistant", "content": "hello"}
    assert response.tool_calls == []
    assert response.usage == {"total_tokens": 7}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_provider.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'agentic_core.providers'
```

- [ ] **Step 3: Add provider base models**

Create `agentic_core/providers/base.py`:

```python
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
```

- [ ] **Step 4: Add OpenAI-compatible adapter**

Create `agentic_core/providers/openai_compatible.py`:

```python
from typing import Any
import json

import httpx

from agentic_core.providers.base import ProviderResponse, ProviderToolCall
from agentic_core.schemas import ProviderConfig


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, client: httpx.Client | None = None):
        if not config.api_key:
            raise ValueError(f"missing API key env var: {config.api_key_env}")
        self.config = config
        self.client = client or httpx.Client(timeout=60)

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float,
    ) -> ProviderResponse:
        base_url = (self.config.base_url or self.config.default_base_url).rstrip("/")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = self.client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]

        tool_calls: list[ProviderToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            tool_calls.append(
                ProviderToolCall(
                    id=call.get("id") or function.get("name") or "tool_call",
                    name=function["name"],
                    arguments=arguments,
                )
            )

        return ProviderResponse(
            message=message,
            tool_calls=tool_calls,
            usage=data.get("usage") or {},
        )
```

- [ ] **Step 5: Add provider factory**

Create `agentic_core/providers/__init__.py`:

```python
from agentic_core.providers.base import Provider
from agentic_core.providers.openai_compatible import OpenAICompatibleProvider
from agentic_core.schemas import ProviderConfig


def build_provider(config: ProviderConfig) -> Provider:
    if config.type == "openai_compatible":
        return OpenAICompatibleProvider(config)
    raise ValueError(f"unsupported provider type: {config.type}")
```

- [ ] **Step 6: Run provider tests and verify they pass**

Run:

```bash
python -m pytest tests/test_provider.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 7: Commit**

```bash
git add agentic_core/providers tests/test_provider.py
git commit -m "Add OpenAI-compatible provider adapter"
```

## Task 5: Agentic Core Chat and Tool Loop

**Files:**
- Modify: `agentic_core/core.py`
- Test: `tests/test_core_loop.py`

- [ ] **Step 1: Write core loop tests**

Create `tests/test_core_loop.py`:

```python
from agentic_core.core import AgenticCore
from agentic_core.providers.base import ProviderResponse, ProviderToolCall
from agentic_core.schemas import AgentConfig, AgenticConfig, PathConfig, ProviderConfig, ToolConfig
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
                tool_calls=[ProviderToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
            )
        return ProviderResponse(
            message={"role": "assistant", "content": "final answer"},
            usage={"total_tokens": 12},
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
    assert result.usage == {"total_tokens": 12}


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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_core_loop.py -q
```

Expected:

```text
TypeError: AgenticCore.__init__() got an unexpected keyword argument 'provider'
```

- [ ] **Step 3: Implement the core loop**

Replace `agentic_core/core.py` with:

```python
from pathlib import Path
from typing import Any

from agentic_core.config import load_agentic_config
from agentic_core.messages import normalize_messages
from agentic_core.providers import build_provider
from agentic_core.providers.base import Provider
from agentic_core.schemas import AgenticConfig, RunResult, ToolCallLog
from agentic_core.tools import build_default_registry
from agentic_core.tools.registry import ToolRegistry


class AgenticCore:
    """Callable Agentic Core component."""

    def __init__(
        self,
        config: AgenticConfig,
        provider: Provider | None = None,
        tools: ToolRegistry | None = None,
    ):
        self.config = config
        self.provider = provider or build_provider(config.provider)
        self.tools = tools or build_default_registry(config.tools)

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

        conversation = [
            {"role": "system", "content": self.config.agent.system_prompt},
            *normalize_messages(messages),
        ]
        tool_logs: list[ToolCallLog] = []
        usage: dict[str, Any] = {}

        for _turn in range(self.config.agent.max_turns):
            response = self.provider.complete(
                messages=conversation,
                tools=self.tools.provider_tools(),
                temperature=self.config.agent.temperature,
            )
            usage.update(response.usage)
            conversation.append(response.message)

            if not response.tool_calls:
                final_text = str(response.message.get("content") or "")
                return RunResult(
                    status="ok",
                    messages=conversation,
                    final_text=final_text,
                    tool_calls=tool_logs,
                    usage=usage,
                )

            for call in response.tool_calls:
                log = ToolCallLog(name=call.name, arguments=call.arguments)
                try:
                    result = self.tools.run(call.name, call.arguments, run_context)
                    log.result = result
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": str(result),
                        }
                    )
                except Exception as exc:
                    log.error = str(exc)
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": f"ERROR: {exc}",
                        }
                    )
                tool_logs.append(log)

        return RunResult(
            status="error",
            messages=conversation,
            tool_calls=tool_logs,
            usage=usage,
            errors=["max turns reached"],
        )
```

- [ ] **Step 4: Run all core package tests**

Run:

```bash
python -m pytest tests/test_imports.py tests/test_config.py tests/test_messages.py tests/test_tools.py tests/test_provider.py tests/test_core_loop.py -q
```

Expected:

```text
14 passed
```

- [ ] **Step 5: Commit**

```bash
git add agentic_core/core.py tests/test_core_loop.py
git commit -m "Add Agentic Core tool loop"
```

## Task 6: CLI Smoke Entry Point

**Files:**
- Create: `agentic_core/run.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write CLI parser test**

Create `tests/test_cli.py`:

```python
from agentic_core.run import parse_args


def test_parse_args_defaults():
    args = parse_args(["--prompt", "hello"])

    assert args.config == "config/agentic-core.yml"
    assert args.prompt == "hello"


def test_parse_args_accepts_config():
    args = parse_args(["--config", "config/agentic-core.example.yml", "--prompt", "hello"])

    assert args.config == "config/agentic-core.example.yml"
    assert args.prompt == "hello"
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
python -m pytest tests/test_cli.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'agentic_core.run'
```

- [ ] **Step 3: Add CLI module**

Create `agentic_core/run.py`:

```python
import argparse
import json

from agentic_core import AgenticCore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Founder Intelligence Agentic Core")
    parser.add_argument("--config", default="config/agentic-core.yml")
    parser.add_argument("--prompt", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    core = AgenticCore.from_config(args.config)
    result = core.run(messages=[{"role": "user", "content": args.prompt}], context={})
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests and verify they pass**

Run:

```bash
python -m pytest tests/test_cli.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add agentic_core/run.py tests/test_cli.py
git commit -m "Add Agentic Core CLI entry point"
```

## Task 7: FastAPI Local Workbench API

**Files:**
- Create: `web_workbench/__init__.py`
- Create: `web_workbench/app.py`
- Test: `tests/test_workbench_api.py`

- [ ] **Step 1: Write FastAPI endpoint tests**

Create `tests/test_workbench_api.py`:

```python
from fastapi.testclient import TestClient

from web_workbench.app import app


def test_health_endpoint():
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_config_endpoint_hides_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    client = TestClient(app)

    response = client.get("/api/default-config")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"]["api_key_configured"] is True
    assert "secret" not in str(data)
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
python -m pytest tests/test_workbench_api.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'web_workbench'
```

- [ ] **Step 3: Add FastAPI app**

Create `web_workbench/__init__.py`:

```python
```

Create `web_workbench/app.py`:

```python
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentic_core import AgenticCore
from agentic_core.config import load_agentic_config
from agentic_core.schemas import AgenticConfig

DEFAULT_CONFIG = Path("config/agentic-core.example.yml")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Founder Intelligence Agentic Core Workbench")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str
    config_path: str = str(DEFAULT_CONFIG)
    context: dict[str, Any] = {}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/default-config")
def default_config() -> dict[str, Any]:
    config: AgenticConfig = load_agentic_config(DEFAULT_CONFIG)
    return {
        "provider": config.provider.safe_dict(),
        "agent": config.agent.model_dump(),
        "tools": {name: tool.model_dump() for name, tool in config.tools.items()},
        "paths": {key: str(value) for key, value in config.paths.model_dump().items()},
    }


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    core = AgenticCore.from_config(request.config_path)
    result = core.run(
        messages=[{"role": "user", "content": request.message}],
        context=request.context,
    )
    return result.model_dump()
```

- [ ] **Step 4: Run API tests and verify they pass**

Run:

```bash
python -m pytest tests/test_workbench_api.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add web_workbench tests/test_workbench_api.py
git commit -m "Add local Agentic Core workbench API"
```

## Task 8: Static Web Workbench UI

**Files:**
- Create: `web_workbench/static/index.html`
- Create: `web_workbench/static/styles.css`
- Create: `web_workbench/static/app.js`

- [ ] **Step 1: Add HTML shell**

Create `web_workbench/static/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Agentic Core Workbench</title>
    <link rel="stylesheet" href="/static/styles.css" />
  </head>
  <body>
    <main class="layout">
      <section class="panel chat-panel">
        <header>
          <h1>Agentic Core</h1>
          <p id="token-status">Checking provider...</p>
        </header>
        <div id="messages" class="messages"></div>
        <form id="chat-form" class="composer">
          <textarea id="message-input" placeholder="Ask about current founder signals"></textarea>
          <button type="submit">Send</button>
        </form>
      </section>

      <aside class="panel side-panel">
        <section>
          <h2>Provider</h2>
          <label>
            Model
            <input id="model-input" readonly />
          </label>
          <label>
            Base URL
            <input id="base-url-input" readonly />
          </label>
        </section>

        <section>
          <h2>Tools</h2>
          <div id="tools"></div>
        </section>

        <section>
          <h2>Tool Calls</h2>
          <pre id="tool-log">[]</pre>
        </section>
      </aside>
    </main>
    <script src="/static/app.js"></script>
  </body>
</html>
```

- [ ] **Step 2: Add CSS**

Create `web_workbench/static/styles.css`:

```css
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f5f7f8;
  color: #172026;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

.layout {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 1px;
  background: #d9e0e4;
}

.panel {
  background: #ffffff;
  padding: 20px;
}

.chat-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 16px;
}

h1,
h2,
p {
  margin-top: 0;
}

.messages {
  overflow: auto;
  border: 1px solid #d9e0e4;
  border-radius: 8px;
  padding: 12px;
  background: #fbfcfd;
}

.message {
  max-width: 820px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #eef3f5;
  white-space: pre-wrap;
}

.message.assistant {
  background: #f1efe7;
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

textarea {
  min-height: 76px;
  resize: vertical;
}

textarea,
input {
  width: 100%;
  border: 1px solid #bfccd3;
  border-radius: 6px;
  padding: 10px;
  font: inherit;
}

button {
  border: 0;
  border-radius: 6px;
  padding: 0 18px;
  font: inherit;
  background: #235789;
  color: #ffffff;
}

.side-panel {
  overflow: auto;
}

.side-panel section {
  margin-bottom: 24px;
}

label {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 14px;
}

.tool-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #e4eaed;
}

pre {
  overflow: auto;
  background: #172026;
  color: #eaf2f5;
  padding: 12px;
  border-radius: 8px;
}

@media (max-width: 860px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Add browser logic**

Create `web_workbench/static/app.js`:

```javascript
const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#chat-form");
const inputEl = document.querySelector("#message-input");
const tokenStatusEl = document.querySelector("#token-status");
const modelInputEl = document.querySelector("#model-input");
const baseUrlInputEl = document.querySelector("#base-url-input");
const toolsEl = document.querySelector("#tools");
const toolLogEl = document.querySelector("#tool-log");

function appendMessage(role, content) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = content;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadConfig() {
  const response = await fetch("/api/default-config");
  const config = await response.json();

  tokenStatusEl.textContent = config.provider.api_key_configured
    ? "API token configured"
    : "API token missing";
  modelInputEl.value = config.provider.model;
  baseUrlInputEl.value = config.provider.base_url;

  toolsEl.innerHTML = "";
  Object.entries(config.tools).forEach(([name, tool]) => {
    const row = document.createElement("div");
    row.className = "tool-row";
    row.innerHTML = `<span>${name}</span><strong>${tool.enabled ? "enabled" : "disabled"}</strong>`;
    toolsEl.appendChild(row);
  });
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message) return;

  appendMessage("user", message);
  inputEl.value = "";

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({message}),
  });
  const result = await response.json();

  appendMessage("assistant", result.final_text || result.errors.join("\\n"));
  toolLogEl.textContent = JSON.stringify(result.tool_calls, null, 2);
});

loadConfig().catch((error) => {
  tokenStatusEl.textContent = `Config error: ${error}`;
});
```

- [ ] **Step 4: Run API tests to ensure UI additions do not break app import**

Run:

```bash
python -m pytest tests/test_workbench_api.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add web_workbench/static
git commit -m "Add local Agentic Core workbench UI"
```

## Task 9: Final Verification and Documentation Touches

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`

- [ ] **Step 1: Update README with local workbench commands**

Append this section to `README.md`:

````markdown
## Agentic Core Workbench

The Agentic Core is a local-only Python component and FastAPI workbench.

Create a local config from the example:

```bash
cp config/agentic-core.example.yml config/agentic-core.yml
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then run:

```bash
python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

The workbench reads existing pipeline artifacts such as `data/signals/latest.json` and writes agentic outputs under `data/agentic/`.
```
````

- [ ] **Step 2: Add docs index entry**

Modify `docs/index.md` by adding this item under Primary Documents:

```markdown
- [Agentic Core Design](superpowers/specs/2026-07-08-agentic-core-design.md): explains the approved Agentic Core component, provider/tool boundaries, local workbench, and security scope.
```

- [ ] **Step 3: Run all tests**

Run:

```bash
python -m pytest -q
```

Expected:

```text
18 passed
```

- [ ] **Step 4: Start local workbench for smoke check**

Run:

```bash
python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 8787
```

Expected terminal output includes:

```text
Uvicorn running on http://127.0.0.1:8787
```

Open `http://127.0.0.1:8787` in a browser. Verify:

- the page loads
- provider model and base URL display
- token status displays configured or missing
- tools list displays `read_signals`, `read_canonical_items`, and `write_agentic_artifact`

- [ ] **Step 5: Stop local server**

Press `Ctrl-C` in the terminal running Uvicorn.

Expected terminal output includes:

```text
Application shutdown complete
```

- [ ] **Step 6: Commit**

```bash
git add README.md docs/index.md
git commit -m "Document Agentic Core workbench"
```

## Final Acceptance Checklist

- [ ] `python -m pytest -q` passes without real API credentials.
- [ ] `python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 8787` starts the local workbench.
- [ ] `/api/default-config` reports token configured status without returning token values.
- [ ] Agentic Core can be imported with `from agentic_core import AgenticCore`.
- [ ] `AgenticCore.run(...)` supports a fake provider tool loop in tests.
- [ ] The current Ruby files under `src/` are unchanged.
- [ ] Existing stable MVP config files are unchanged except for the new `config/agentic-core.example.yml`.
- [ ] No generated `.env`, local token, or `data/agentic/` output is committed.
