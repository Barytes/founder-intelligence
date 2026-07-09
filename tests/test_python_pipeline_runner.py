import json
import os
import sys
from pathlib import Path

from web_workbench.pipeline_runner import PipelineRunner


def test_successful_refresh_publishes_validated_temp_signals(tmp_path):
    write_json(tmp_path, "data/signals/latest.json", sample_signal_output("run-old"))
    runner = PipelineRunner(
        root=tmp_path,
        commands=[
            write_json_command(
                "adapter",
                "data/adapter-output/rss-fetch-latest.json",
                {
                    "results": [
                        {"source_id": "github-trending-daily", "status": "failed", "items": [], "errors": []},
                        {"source_id": "zhihu-hot", "status": "ok", "items": [{"title": "item"}], "errors": []},
                    ]
                },
            ),
            write_json_command("canonical", "data/canonical-items/latest.json", {"run_id": "run-new", "items": []}),
            append_jsonl_command(
                "store",
                "data/store/runs/2026-07-08.jsonl",
                {"input_run_id": "run-new"},
                stdout={"input_items": 1, "appended_items": 1, "skipped_duplicates": 0},
            ),
            write_json_command("signals", "data/app/tmp/$REQUEST_ID/signals.json", sample_signal_output("run-new")),
        ],
        timeout_seconds=5,
    )

    status = runner.refresh()

    assert status["status"] == "succeeded"
    assert status["adapter_summary"] == {
        "total_sources": 2,
        "ok_sources": 1,
        "partial_sources": 0,
        "failed_sources": 1,
        "items": 1,
        "source_results": [
            {"source_id": "github-trending-daily", "status": "failed", "item_count": 0, "errors": []},
            {"source_id": "zhihu-hot", "status": "ok", "item_count": 1, "errors": []},
        ],
    }
    assert status["store_summary"] == {
        "input_items": 1,
        "appended_items": 1,
        "skipped_duplicates": 0,
    }
    assert status["signal_diff"]["changed"] is False
    assert read_json(tmp_path, "data/signals/latest.json")["input_run_id"] == "run-new"
    assert read_json(tmp_path, "data/app/refresh-status.json")["status"] == "succeeded"


def test_failed_refresh_does_not_overwrite_previous_successful_signals(tmp_path):
    write_json(tmp_path, "data/signals/latest.json", sample_signal_output("run-old"))
    before = (tmp_path / "data/signals/latest.json").read_text(encoding="utf-8")
    runner = PipelineRunner(
        root=tmp_path,
        commands=[
            write_json_command("adapter", "data/adapter-output/rss-fetch-latest.json", {"status": "ok"}),
            failing_command("canonical"),
        ],
        timeout_seconds=5,
    )

    status = runner.refresh()

    assert status["status"] == "failed"
    assert (tmp_path / "data/signals/latest.json").read_text(encoding="utf-8") == before
    assert read_json(tmp_path, "data/signals/latest.json")["input_run_id"] == "run-old"


def test_refresh_is_rejected_when_lock_exists_for_running_process(tmp_path):
    lock_path = tmp_path / "data/app/refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"request_id": "held", "pid": os.getpid(), "started_at": "2026-07-09T00:00:00+00:00"}),
        encoding="utf-8",
    )
    runner = PipelineRunner(root=tmp_path, commands=[], timeout_seconds=5)

    status = runner.refresh()

    assert status["status"] == "already_running"


def write_json_command(name, path, value):
    code = (
        "import json, os, pathlib, sys; "
        "path = pathlib.Path(sys.argv[1].replace('$REQUEST_ID', os.environ['REQUEST_ID'])); "
        "path.parent.mkdir(parents=True, exist_ok=True); "
        "path.write_text(json.dumps(json.loads(sys.argv[2])), encoding='utf-8')"
    )
    return {"name": name, "argv": [sys.executable, "-c", code, path, json.dumps(value)]}


def append_jsonl_command(name, path, value, stdout=None):
    code = (
        "import json, pathlib, sys; "
        "path = pathlib.Path(sys.argv[1]); "
        "path.parent.mkdir(parents=True, exist_ok=True); "
        "path.open('a', encoding='utf-8').write(json.dumps(json.loads(sys.argv[2])) + '\\n'); "
        "print(sys.argv[3]) if sys.argv[3] else None"
    )
    return {
        "name": name,
        "argv": [sys.executable, "-c", code, path, json.dumps(value), json.dumps(stdout or {}) if stdout else ""],
    }


def failing_command(name):
    return {"name": name, "argv": [sys.executable, "-c", "import sys; sys.exit(7)"]}


def write_json(root, path, value):
    full_path = Path(root) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_json(root, path):
    return json.loads((Path(root) / path).read_text(encoding="utf-8"))


def sample_signal_output(run_id):
    return {
        "contract_version": 1,
        "generated_at": "2026-07-08T10:00:00+08:00",
        "input_run_id": run_id,
        "summary": {"input_items": 1, "signals": 1, "top_n": 10},
        "signals": [{"id": "signal-1", "title": "Signal 1", "total_score": 4.2}],
    }
