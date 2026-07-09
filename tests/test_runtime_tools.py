import json
from pathlib import Path

from agentic_core.tools.runtime_tools import read_latest_run, read_refresh_status


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_read_refresh_status_returns_idle_when_missing(tmp_path):
    result = read_refresh_status({}, {"repo_root": str(tmp_path)})

    assert result == {
        "status": "idle",
        "message": "No refresh status has been recorded yet.",
    }


def test_read_refresh_status_reads_fixed_file(tmp_path):
    write_json(tmp_path / "data/app/refresh-status.json", {"status": "succeeded"})

    result = read_refresh_status({}, {"repo_root": str(tmp_path)})

    assert result["status"] == "succeeded"


def test_read_latest_run_returns_latest_jsonl_record(tmp_path):
    runs = tmp_path / "data/store/runs/2026-07-09.jsonl"
    runs.parent.mkdir(parents=True, exist_ok=True)
    runs.write_text(
        json.dumps({"input_run_id": "run-old"})
        + "\n"
        + json.dumps({"input_run_id": "run-new"})
        + "\n",
        encoding="utf-8",
    )

    result = read_latest_run({}, {"repo_root": str(tmp_path)})

    assert result["status"] == "ok"
    assert result["run"]["input_run_id"] == "run-new"
    assert result["path"] == "data/store/runs/2026-07-09.jsonl"
