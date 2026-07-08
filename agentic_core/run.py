import argparse
import json

from agentic_core import AgenticCore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Founder Intelligence Agentic Core")
    parser.add_argument("--config", default="config/agentic-core.yml")
    parser.add_argument("--prompt", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        core = AgenticCore.from_config(args.config)
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

    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
