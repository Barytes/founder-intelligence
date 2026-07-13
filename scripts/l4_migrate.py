#!/usr/bin/env python3
"""Repository-local entrypoint for the L4 semantic migration."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/agentic-core"))

from agentic_core.l4.migration import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
