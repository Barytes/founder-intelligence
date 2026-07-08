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
