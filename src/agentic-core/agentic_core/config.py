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


def _read_optional_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return _read_yaml(path)


def _default_local_config_path(path: Path) -> Path | None:
    if path.name in {"agentic-core.example.yml", "agentic-core.example.yaml"}:
        return path.with_name("agentic-core.local.yml")
    return None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _map_legacy_provider_overrides(
    base: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    if "provider_profiles" in overlay:
        return overlay

    provider = overlay.get("provider")
    profiles = base.get("provider_profiles")
    if not isinstance(provider, dict) or not isinstance(profiles, dict):
        return overlay

    active = profiles.get("active")
    if not isinstance(active, str):
        return overlay

    profile_overlay = {
        key: provider[key]
        for key in ("base_url", "model")
        if isinstance(provider.get(key), str)
    }
    if not profile_overlay:
        return overlay

    return _deep_merge(
        overlay,
        {"provider_profiles": {"items": {active: profile_overlay}}},
    )


def _provider_from_active_profile(config: AgenticConfig):
    if config.provider_profiles is None:
        return config.provider

    active = config.provider_profiles.active
    profile = config.provider_profiles.items.get(active)
    if profile is None:
        raise ValueError(f"active provider profile not found: {active}")

    return config.provider.model_copy(
        update={
            "type": profile.type,
            "api_key_env": profile.api_key_env,
            "base_url_env": None,
            "default_base_url": profile.base_url,
            "base_url": profile.base_url,
            "model": profile.model,
        }
    )


def load_agentic_config(
    config_path: str | Path,
    *,
    local_config_path: str | Path | None = None,
) -> AgenticConfig:
    load_dotenv()
    path = Path(config_path)
    local_path = (
        Path(local_config_path)
        if local_config_path is not None
        else _default_local_config_path(path)
    )
    base_data = _read_yaml(path)
    local_data = _map_legacy_provider_overrides(
        base_data,
        _read_optional_yaml(local_path),
    )
    data = _deep_merge(base_data, local_data)
    config = AgenticConfig.model_validate(data)
    provider = _provider_from_active_profile(config)

    api_key = os.environ.get(provider.api_key_env)
    base_url = (
        os.environ.get(provider.base_url_env)
        if provider.base_url_env
        else None
    )

    return config.model_copy(
        update={
            "provider": provider.model_copy(
                update={
                    "api_key": api_key,
                    "base_url": base_url or provider.base_url or provider.default_base_url,
                }
            )
        }
    )
