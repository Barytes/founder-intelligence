import json
from pathlib import Path
from typing import Any


def _repo_root(context: dict[str, Any]) -> Path:
    return Path(context.get("repo_root") or Path.cwd()).resolve()


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def read_refresh_status(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    root = _repo_root(context)
    path = root / "data" / "app" / "refresh-status.json"
    if not path.exists():
        return {"status": "idle", "message": "No refresh status has been recorded yet."}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_latest_run(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    root = _repo_root(context)
    run_files = sorted((root / "data" / "store" / "runs").glob("*.jsonl"))
    if not run_files:
        return {"status": "empty", "message": "No store runs have been recorded yet."}

    latest_run_path = run_files[-1]
    for line in reversed(latest_run_path.read_text(encoding="utf-8").splitlines()):
        if line.strip():
            return {
                "status": "ok",
                "path": _relative(latest_run_path, root),
                "run": json.loads(line),
            }
    return {"status": "empty", "message": "Latest run file has no records."}
