from pathlib import Path
import json
from typing import Any


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "config").is_dir() and (candidate / "AGENTS.md").exists():
            return candidate
    return start.parents[2]


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
ARTIFACT_ROOT = REPO_ROOT / "data" / "agentic"


def _normalize_path(path: str | Path) -> Path:
    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = REPO_ROOT / path_obj
    return path_obj.resolve()


def _require_path_in_repo(path: Path) -> Path:
    if not path.is_relative_to(REPO_ROOT):
        raise ValueError(f"path outside repository: {path}")
    return path


def _require_artifact_dir_within_data_agentic(path: Path) -> Path:
    if not path.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"artifact_dir outside data/agentic: {path}")
    return path


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"artifact not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_signals(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    path = _normalize_path(
        arguments.get("path") or context.get("signals_path") or "data/signals/latest.json"
    )
    return _read_json(_require_path_in_repo(path))


def read_canonical_items(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    path = _normalize_path(
        arguments.get("path")
        or context.get("canonical_items_path")
        or "data/canonical-items/latest.json"
    )
    return _read_json(_require_path_in_repo(path))


def write_agentic_artifact(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, list[str]]:
    artifact_dir = _normalize_path(context.get("artifact_dir") or str(ARTIFACT_ROOT))
    artifact_dir = _require_artifact_dir_within_data_agentic(artifact_dir)
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
