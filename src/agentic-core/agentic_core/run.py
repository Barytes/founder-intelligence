import argparse
import json
from pathlib import Path

from agentic_core import AgenticCore

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Founder Intelligence Agentic Core")
    parser.add_argument("--config", default="config/agentic-core.yml")
    parser.add_argument("--prompt", required=True)
    return parser.parse_args(argv)


def _resolve_config_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = REPO_ROOT / path

    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("config path outside repository") from exc

    if resolved.suffix.lower() not in {".yml", ".yaml"}:
        raise ValueError("config path must be YAML")

    return resolved


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    core: AgenticCore | None = None
    try:
        config_path = _resolve_config_path(args.config)
        core = AgenticCore.from_config(config_path)
        result = core.run(messages=[{"role": "user", "content": args.prompt}], context={})
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "messages": [],
                    "final_text": "",
                    "tool_calls": [],
                    "artifact_paths": [],
                    "usage": {},
                    "errors": [str(exc)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    finally:
        if core is not None:
            close = getattr(core, "close", None)
            if callable(close):
                close()

    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
