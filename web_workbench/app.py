from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agentic_core import AgenticCore
from agentic_core.config import load_agentic_config
from agentic_core.schemas import AgenticConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config/agentic-core.example.yml"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Founder Intelligence Agentic Core Workbench")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str
    config_path: str = str(DEFAULT_CONFIG)
    context: dict[str, Any] = Field(default_factory=dict)


def _error_result(error: str) -> dict[str, Any]:
    return {
        "status": "error",
        "messages": [],
        "final_text": "",
        "tool_calls": [],
        "artifact_paths": [],
        "usage": {},
        "errors": [error],
    }


def _resolve_config_path(config_path: str) -> tuple[Path, None] | tuple[None, str]:
    requested = Path(config_path)
    candidate = requested if requested.is_absolute() else REPO_ROOT / requested
    normalized = candidate.resolve()

    if not normalized.is_relative_to(REPO_ROOT):
        return None, f"config path outside repository: {config_path}"

    if normalized.suffix.lower() not in {".yml", ".yaml"}:
        return None, f"config path must be YAML: {config_path}"

    return normalized, None


@app.get("/", response_model=None)
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "status": "missing_ui",
        "message": "Workbench UI has not been built yet.",
    }


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
    resolved_path, error = _resolve_config_path(request.config_path)
    if error is not None:
        return _error_result(error)

    try:
        core = AgenticCore.from_config(resolved_path)
        result = core.run(
            messages=[{"role": "user", "content": request.message}],
            context=request.context,
        )
        return result.model_dump()
    except Exception as exc:
        return _error_result(str(exc))
