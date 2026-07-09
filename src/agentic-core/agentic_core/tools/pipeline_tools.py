from pathlib import Path
from typing import Any

from agentic_core.pipeline.runner import PipelineRunner


ALLOWED_ARGUMENTS = {"reason"}


def _repo_root(context: dict[str, Any]) -> Path:
    return Path(context.get("repo_root") or Path.cwd()).resolve()


def run_refresh_pipeline(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    unexpected = sorted(set(arguments) - ALLOWED_ARGUMENTS)
    if unexpected:
        return {
            "status": "error",
            "error_type": "invalid_arguments",
            "message": f"Unsupported arguments: {', '.join(unexpected)}",
        }

    root = _repo_root(context)
    try:
        return PipelineRunner(
            root=root,
            timeout_seconds=int(context.get("refresh_timeout_seconds") or 180),
        ).refresh()
    except Exception as exc:
        return {
            "status": "error",
            "error_type": "runner_failed",
            "message": str(exc),
        }
