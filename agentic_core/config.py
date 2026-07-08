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
