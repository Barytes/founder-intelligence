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
