from pathlib import Path
from contextlib import asynccontextmanager
import json
import os
import re
import subprocess
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import yaml

from agentic_core import AgenticCore
from agentic_core.config import load_agentic_config
from agentic_core.pipeline.runner import PipelineRunner
from agentic_core.schemas import AgenticConfig, ProviderProfileConfig
from web_workbench.dashboard_repository import DashboardRepository


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "config").is_dir() and (candidate / "AGENTS.md").exists():
            return candidate
    return start.parents[1]


CODE_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
REPO_ROOT = Path(os.environ["FI_REPO_ROOT"]).resolve() if os.environ.get("FI_REPO_ROOT") else CODE_REPO_ROOT
DEFAULT_CONFIG = REPO_ROOT / "config/agentic-core.example.yml"
LOCAL_CONFIG = REPO_ROOT / "config/agentic-core.local.yml"
ENV_PATH = REPO_ROOT / ".env"
STATIC_DIR = Path(__file__).parent / "static"
DASHBOARD_PUBLIC_DIR = CODE_REPO_ROOT / "src/web/public"
PROVIDER_TEMPLATE_IDS = ("openai", "deepseek", "openrouter", "custom")
NEW_CONFIG_ID = "__new__"
DISALLOWED_REFRESH_KEYS = {"command", "script", "path", "argv", "args"}
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:4567", "http://localhost:4567")


@asynccontextmanager
async def _lifespan(application: FastAPI):
    if getattr(application.state, "auto_start_rsshub", False):
        application.state.rsshub_start_result = ensure_rsshub(application.state.dashboard_root)
    yield


app = FastAPI(title="Founder Intelligence Agentic Core Workbench", lifespan=_lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/agent/static", StaticFiles(directory=STATIC_DIR), name="agent-static")


def create_app(
    *,
    repo_root: Path | str | None = None,
    runner: Any | None = None,
    allowed_origins: list[str] | tuple[str, ...] | None = None,
    auto_start_rsshub: bool | None = None,
) -> FastAPI:
    root = Path(repo_root or REPO_ROOT).resolve()
    dashboard_public_dir = root / "src/web/public"
    origin_values = allowed_origins or _allowed_origins_from_env() or DEFAULT_ALLOWED_ORIGINS
    app.state.dashboard_root = root
    app.state.dashboard_public_dir = dashboard_public_dir if dashboard_public_dir.exists() else DASHBOARD_PUBLIC_DIR
    app.state.dashboard_runner = runner or PipelineRunner(root=root)
    app.state.auto_start_rsshub = (
        auto_start_rsshub
        if auto_start_rsshub is not None
        else _auto_start_rsshub_from_env()
    )
    app.state.rsshub_start_result = {"status": "disabled"}
    app.state.allowed_origins = {
        normalized
        for normalized in (_normalize_origin(origin) for origin in origin_values)
        if normalized
    }
    return app


def _auto_start_rsshub_from_env() -> bool:
    raw = os.environ.get("FI_AUTO_START_RSSHUB")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _allowed_origins_from_env() -> list[str]:
    raw = os.environ.get("FI_ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _dashboard_repository() -> DashboardRepository:
    return DashboardRepository(root=app.state.dashboard_root)


def _dashboard_public_path(name: str) -> Path:
    return Path(app.state.dashboard_public_dir) / name


def _normalize_origin(value: str) -> str | None:
    parsed = urlparse(str(value))
    if parsed.scheme != "http" or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port and parsed.port != 80 else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _request_origin(request: Request) -> str | None:
    url = request.url
    if not url.scheme or not url.hostname:
        return None
    port = f":{url.port}" if url.port and url.port != 80 else ""
    return f"{url.scheme}://{url.hostname}{port}"


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    normalized = _normalize_origin(origin)
    return bool(
        normalized
        and (normalized in app.state.allowed_origins or normalized == _request_origin(request))
    )


def ensure_rsshub(
    root: Path | str,
    *,
    force_recreate: bool = False,
    run_command: Any | None = None,
) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    compose_file = repo_root / "config/docker-compose.yml"
    if not compose_file.exists():
        return {"status": "skipped", "message": "config/docker-compose.yml is missing."}

    env_file = repo_root / ".env"
    if not env_file.exists():
        env_file.write_text("", encoding="utf-8")

    command = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    if force_recreate:
        command.append("--force-recreate")
    command.append("rsshub")
    runner = run_command or (
        lambda argv: subprocess.run(
            argv,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    )
    try:
        runner(command)
    except Exception as exc:
        return {"status": "error", "command": command, "message": str(exc)}
    return {"status": "started", "command": command}


async def _json_payload(request: Request) -> dict[str, Any] | None:
    body = await request.body()
    if not body or not body.strip():
        return {}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


class ChatRequest(BaseModel):
    message: str
    config_path: str = str(DEFAULT_CONFIG)
    context: dict[str, Any] = Field(default_factory=dict)


class ProviderSettingsRequest(BaseModel):
    config_id: str | None = None
    config_name: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class EnvSettingsRequest(BaseModel):
    github_token: str | None = None


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


def _settings_error(error: str) -> dict[str, Any]:
    return {
        "status": "error",
        "provider": None,
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


def _clean_env_value(label: str, value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None
    if "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} must not contain newlines")
    return cleaned


def _env_file_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key = _env_key_from_line(line)
        if key and "=" in line:
            values[key] = line.split("=", 1)[1].strip()
    return values


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return f"{value[0]}...{value[-1]}"
    return f"{value[:4]}...{value[-4:]}"


def _env_settings_payload() -> dict[str, Any]:
    env_values = _env_file_values(ENV_PATH)
    github_token = os.environ.get("GITHUB_ACCESS_TOKEN") or env_values.get("GITHUB_ACCESS_TOKEN")
    return {
        "github_token": {
            "env_key": "GITHUB_ACCESS_TOKEN",
            "configured": bool(github_token),
            "preview": _mask_secret(github_token),
        }
    }


def _custom_provider_identity(name: str) -> tuple[str, str]:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    env_prefix = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    if not normalized or not env_prefix:
        raise ValueError("Custom provider name must contain letters or numbers")
    return normalized, f"{env_prefix}_LLM_API_KEY"


def _clean_config_name(name: str | None) -> str | None:
    cleaned = _clean_env_value("Config name", name)
    return cleaned


def _env_key_from_line(line: str) -> str | None:
    if "=" not in line:
        return None

    lhs = line.split("=", 1)[0].strip()
    if lhs.startswith("export "):
        lhs = lhs.removeprefix("export ").strip()
    return lhs or None


def _write_env_updates(env_path: Path, updates: dict[str, str]) -> None:
    existing_lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else []
    )
    written_keys: set[str] = set()
    next_lines: list[str] = []

    for line in existing_lines:
        key = _env_key_from_line(line)
        if key in updates:
            next_lines.append(f"{key}={updates[key]}")
            written_keys.add(key)
        else:
            next_lines.append(line)

    for key, value in updates.items():
        if key not in written_keys:
            next_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


def _read_local_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"local config must contain a mapping: {path}")
    return data


def _write_local_model(path: Path, model: str) -> None:
    data = _read_local_config(path)
    provider = data.get("provider")
    if not isinstance(provider, dict):
        provider = {}
        data["provider"] = provider
    provider["model"] = model
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_local_profile(
    path: Path,
    provider_id: str,
    *,
    profile: Any,
    label: str | None = None,
    api_key_env: str | None = None,
    template: str | None = None,
    base_url: str | None,
    model: str | None,
) -> None:
    data = _read_local_config(path)
    profiles = data.get("provider_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        data["provider_profiles"] = profiles

    profiles["active"] = provider_id
    items = profiles.get("items")
    if not isinstance(items, dict):
        items = {}
        profiles["items"] = items

    profile_data = items.get(provider_id)
    if not isinstance(profile_data, dict):
        profile_data = {}
        items[provider_id] = profile_data

    profile_data["label"] = label or profile.label
    if template is not None:
        profile_data["template"] = template
    profile_data["type"] = profile.type
    profile_data["api_key_env"] = api_key_env or profile.api_key_env
    profile_data["base_url"] = base_url or profile.base_url
    profile_data["model"] = model or profile.model

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _provider_profiles_payload(config: AgenticConfig) -> dict[str, Any] | None:
    profiles = config.provider_profiles
    if profiles is None:
        return None

    return {
        "active": profiles.active,
        "items": {
            profile_id: {
                "label": profile.label,
                "template": profile.template
                or (profile_id if profile_id in PROVIDER_TEMPLATE_IDS else "custom"),
                "type": profile.type,
                "api_key_env": profile.api_key_env,
                "api_key_configured": bool(os.environ.get(profile.api_key_env)),
                "base_url": profile.base_url,
                "model": profile.model,
            }
            for profile_id, profile in profiles.items.items()
        },
    }


def _provider_templates_payload(config: AgenticConfig) -> dict[str, Any] | None:
    profiles = config.provider_profiles
    if profiles is None:
        return None
    items = _provider_profiles_payload(config)["items"]
    return {
        "items": {
            profile_id: items[profile_id]
            for profile_id in PROVIDER_TEMPLATE_IDS
            if profile_id in items
        }
    }


def _local_profile_ids(path: Path) -> set[str]:
    data = _read_local_config(path)
    items = data.get("provider_profiles", {}).get("items", {})
    if not isinstance(items, dict):
        return set()
    return {profile_id for profile_id in items if isinstance(profile_id, str)}


def _saved_configs_payload(
    config: AgenticConfig,
    local_config_path: Path | None = None,
) -> dict[str, Any] | None:
    profiles_payload = _provider_profiles_payload(config)
    if profiles_payload is None:
        return None
    local_config_path = local_config_path or LOCAL_CONFIG
    saved_ids = _local_profile_ids(local_config_path)
    items = {
        profile_id: profile
        for profile_id, profile in profiles_payload["items"].items()
        if profile_id in saved_ids
    }
    active = profiles_payload["active"] if profiles_payload["active"] in items else None
    return {
        "active": active,
        "items": items,
    }


@app.get("/agent", response_model=None)
def agent_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "status": "missing_ui",
        "message": "Workbench UI has not been built yet.",
    }


@app.get("/settings", response_model=None)
def settings_index():
    settings_file = STATIC_DIR / "settings.html"
    if settings_file.exists():
        return FileResponse(settings_file)
    return {
        "status": "missing_ui",
        "message": "Settings UI has not been built yet.",
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_model=None)
def dashboard_index():
    return FileResponse(_dashboard_public_path("index.html"))


@app.get("/app.js", response_model=None)
def dashboard_app_js():
    return FileResponse(_dashboard_public_path("app.js"), media_type="application/javascript")


@app.get("/styles.css", response_model=None)
def dashboard_styles():
    return FileResponse(_dashboard_public_path("styles.css"), media_type="text/css")


@app.get("/assets/{asset_path:path}", response_model=None)
def dashboard_asset(asset_path: str):
    assets_root = _dashboard_public_path("assets").resolve()
    path = (assets_root / asset_path).resolve()
    if not str(path).startswith(f"{assets_root}/") or not path.is_file():
        return JSONResponse({"status": "not_found"}, status_code=404)
    return FileResponse(path)


@app.get("/api/signals/latest")
def latest_signals() -> dict[str, Any]:
    return _dashboard_repository().latest_signals()


@app.get("/api/runs/latest")
def latest_run() -> dict[str, Any]:
    return _dashboard_repository().latest_run()


@app.get("/api/refresh/status")
def refresh_status() -> dict[str, Any]:
    return _dashboard_repository().refresh_status()


@app.get("/api/profile")
def profile() -> dict[str, Any]:
    return _dashboard_repository().profile()


@app.put("/api/profile")
async def update_profile(request: Request):
    if not _same_origin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    payload = await _json_payload(request)
    if payload is None:
        return JSONResponse({"status": "bad_request", "message": "Invalid JSON body."}, status_code=400)
    result = _dashboard_repository().update_profile(payload.get("content"))
    return JSONResponse(result, status_code=200 if result.get("status") == "saved" else 400)


@app.get("/api/sources")
def sources() -> dict[str, Any]:
    return _dashboard_repository().sources()


@app.put("/api/sources")
async def update_sources(request: Request):
    if not _same_origin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    payload = await _json_payload(request)
    if payload is None:
        return JSONResponse({"status": "bad_request", "message": "Invalid JSON body."}, status_code=400)
    result = _dashboard_repository().update_sources(payload.get("content"))
    return JSONResponse(result, status_code=200 if result.get("status") == "saved" else 400)


@app.post("/api/sources/{source_id}")
@app.patch("/api/sources/{source_id}")
async def update_source_enabled(source_id: str, request: Request):
    if not _same_origin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    payload = await _json_payload(request)
    if payload is None:
        return JSONResponse({"status": "bad_request", "message": "Invalid JSON body."}, status_code=400)
    result = _dashboard_repository().update_source_enabled(source_id, payload.get("enabled"))
    status_code = 200 if result.get("status") == "saved" else 404 if result.get("status") == "not_found" else 400
    return JSONResponse(result, status_code=status_code)


@app.post("/api/refresh")
async def refresh(request: Request):
    if not _same_origin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    payload = await _json_payload(request)
    if payload is None:
        return JSONResponse({"status": "bad_request", "message": "Invalid JSON body."}, status_code=400)
    if DISALLOWED_REFRESH_KEYS.intersection(str(key) for key in payload.keys()):
        return JSONResponse(
            {"status": "bad_request", "message": "Refresh does not accept command parameters."},
            status_code=400,
        )
    result = app.state.dashboard_runner.refresh()
    return JSONResponse(result, status_code=409 if result.get("status") == "already_running" else 200)


@app.get("/api/agent/default-config")
@app.get("/api/default-config")
def default_config() -> dict[str, Any]:
    config: AgenticConfig = load_agentic_config(
        DEFAULT_CONFIG,
        local_config_path=LOCAL_CONFIG,
    )
    return {
        "provider": config.provider.safe_dict(),
        "provider_profiles": _provider_profiles_payload(config),
        "provider_templates": _provider_templates_payload(config),
        "saved_configs": _saved_configs_payload(config),
        "agent": config.agent.model_dump(),
        "tools": {name: tool.model_dump() for name, tool in config.tools.items()},
        "paths": {key: str(value) for key, value in config.paths.model_dump().items()},
    }


@app.get("/api/settings/env")
def env_settings() -> dict[str, Any]:
    return _env_settings_payload()


@app.put("/api/settings/env")
async def update_env_settings(request: Request):
    if not _same_origin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    payload = await _json_payload(request)
    if payload is None:
        return JSONResponse({"status": "bad_request", "message": "Invalid JSON body."}, status_code=400)

    try:
        settings = EnvSettingsRequest.model_validate(payload)
        github_token = _clean_env_value("GitHub token", settings.github_token)
    except ValueError as exc:
        return JSONResponse({"status": "error", "errors": [str(exc)]}, status_code=400)

    if github_token is None:
        return JSONResponse(
            {"status": "error", "errors": ["GitHub token is required."]},
            status_code=400,
        )

    _write_env_updates(ENV_PATH, {"GITHUB_ACCESS_TOKEN": github_token})
    os.environ["GITHUB_ACCESS_TOKEN"] = github_token
    load_dotenv(ENV_PATH, override=True)
    rsshub = ensure_rsshub(app.state.dashboard_root, force_recreate=True)
    return {
        "status": "saved",
        **_env_settings_payload(),
        "rsshub": rsshub,
        "errors": [],
    }


@app.post("/api/agent/provider-settings")
@app.post("/api/provider-settings")
def save_provider_settings(request: Request, settings: ProviderSettingsRequest):
    if not _same_origin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    try:
        config_id = _clean_env_value("Config", settings.config_id)
        config_name = _clean_config_name(settings.config_name or settings.provider_name)
        provider_id = _clean_env_value("Provider", settings.provider_id)
        api_key = _clean_env_value("API key", settings.api_key)
        base_url = _clean_env_value("Base URL", settings.base_url)
        model = _clean_env_value("Model", settings.model)
    except ValueError as exc:
        return _settings_error(str(exc))

    if api_key is None and base_url is None and model is None:
        return _settings_error("Provide an API key, base URL, or model to save")

    config: AgenticConfig = load_agentic_config(
        DEFAULT_CONFIG,
        local_config_path=LOCAL_CONFIG,
    )
    if config.provider_profiles is not None:
        config_id = None if config_id == NEW_CONFIG_ID else config_id
        if config_id is not None:
            existing_profile = config.provider_profiles.items.get(config_id)
            if existing_profile is None:
                return _settings_error(f"Unknown saved config: {config_id}")
            provider_id = provider_id or existing_profile.template or (
                config_id if config_id in PROVIDER_TEMPLATE_IDS else "custom"
            )
            profile = existing_profile
            target_profile_id = config_id
            target_label = config_name or existing_profile.label
            target_api_key_env = existing_profile.api_key_env
            target_template = provider_id
        else:
            provider_id = provider_id or config.provider_profiles.active
            template_profile = config.provider_profiles.items.get(provider_id)
            if template_profile is None:
                return _settings_error(f"Unknown provider profile: {provider_id}")
            if config_name is None:
                if provider_id == "custom":
                    return _settings_error("Config name is required")
                target_profile_id = provider_id
                target_label = template_profile.label
                target_api_key_env = template_profile.api_key_env
            else:
                try:
                    target_profile_id, target_api_key_env = _custom_provider_identity(
                        config_name
                    )
                except ValueError as exc:
                    return _settings_error(str(exc))
                if (
                    target_profile_id in config.provider_profiles.items
                    and target_profile_id != provider_id
                ):
                    return _settings_error(
                        f"Config name conflicts with existing profile: {target_profile_id}"
                    )
                target_label = config_name
            target_template = provider_id
            profile = template_profile

        if provider_id == "custom" and config_name is not None:
            try:
                custom_provider_id, custom_api_key_env = _custom_provider_identity(
                    config_name
                )
            except ValueError as exc:
                return _settings_error(str(exc))
            if (
                custom_provider_id in config.provider_profiles.items
                and custom_provider_id != "custom"
            ):
                return _settings_error(
                    f"Custom provider name conflicts with existing profile: {custom_provider_id}"
                )
            template_profile = config.provider_profiles.items.get("custom")
            if template_profile is None:
                return _settings_error("Custom provider template is missing")
            target_profile_id = custom_provider_id
            target_api_key_env = custom_api_key_env
            target_label = config_name
            target_template = "custom"
            profile = ProviderProfileConfig(
                label=config_name,
                template="custom",
                type=template_profile.type,
                api_key_env=custom_api_key_env,
                base_url=base_url or template_profile.base_url,
                model=model or template_profile.model,
            )
    else:
        profile = None
        target_profile_id = provider_id
        target_label = config_name
        target_api_key_env = config.provider.api_key_env
        target_template = None

    updates: dict[str, str] = {}
    if api_key is not None:
        updates[target_api_key_env] = api_key
    if (
        profile is None
        and base_url is not None
        and config.provider.base_url_env is not None
    ):
        updates[config.provider.base_url_env] = base_url

    if updates:
        _write_env_updates(ENV_PATH, updates)

    for key, value in updates.items():
        os.environ[key] = value
    if updates:
        load_dotenv(ENV_PATH, override=True)

    if profile is not None and target_profile_id is not None:
        _write_local_profile(
            LOCAL_CONFIG,
            target_profile_id,
            profile=profile,
            label=target_label,
            api_key_env=target_api_key_env,
            template=target_template,
            base_url=base_url,
            model=model,
        )
    elif model is not None:
        _write_local_model(LOCAL_CONFIG, model)

    updated_config = load_agentic_config(
        DEFAULT_CONFIG,
        local_config_path=LOCAL_CONFIG,
    )
    return {
        "status": "ok",
        "provider": updated_config.provider.safe_dict(),
        "provider_profiles": _provider_profiles_payload(updated_config),
        "provider_templates": _provider_templates_payload(updated_config),
        "saved_configs": _saved_configs_payload(updated_config),
        "errors": [],
    }


@app.post("/api/agent/chat")
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


create_app()
