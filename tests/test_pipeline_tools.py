from agentic_core.tools.pipeline_tools import run_refresh_pipeline


def test_run_refresh_pipeline_calls_python_runner(monkeypatch, tmp_path):
    captured = {}

    class FakeRunner:
        def __init__(self, *, root, timeout_seconds):
            captured["root"] = root
            captured["timeout_seconds"] = timeout_seconds

        def refresh(self):
            return {"status": "succeeded"}

    monkeypatch.setattr("agentic_core.tools.pipeline_tools.PipelineRunner", FakeRunner)

    result = run_refresh_pipeline({"reason": "manual refresh"}, {"repo_root": str(tmp_path)})

    assert result["status"] == "succeeded"
    assert captured["root"] == tmp_path
    assert captured["timeout_seconds"] == 180


def test_run_refresh_pipeline_rejects_unknown_arguments(tmp_path):
    result = run_refresh_pipeline({"command": "whoami"}, {"repo_root": str(tmp_path)})

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_arguments"
