import json

import pytest

from agentic_core.schemas import RunResult
import agentic_core.run as cli


def test_parse_args_defaults():
    args = cli.parse_args(["--prompt", "hello"])

    assert args.config == "config/agentic-core.yml"
    assert args.prompt == "hello"


def test_parse_args_accepts_config():
    args = cli.parse_args(["--config", "config/agentic-core.example.yml", "--prompt", "hello"])

    assert args.config == "config/agentic-core.example.yml"
    assert args.prompt == "hello"


def test_parse_args_requires_prompt():
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_main_returns_ok_result(monkeypatch, capsys):
    fake_result = RunResult(status="ok", messages=[], final_text="ok")

    class FakeCore:
        @classmethod
        def from_config(cls, _config):
            return cls()

        def run(self, **_kwargs):
            return fake_result

    monkeypatch.setattr(cli, "AgenticCore", FakeCore)

    exit_code = cli.main(["--prompt", "hello"])
    captured = capsys.readouterr().out
    payload = json.loads(captured)

    assert exit_code == 0
    assert payload["status"] == "ok"


def test_main_handles_init_errors(monkeypatch, capsys):
    class FakeCore:
        @classmethod
        def from_config(cls, _config):
            raise FileNotFoundError("missing config")

    monkeypatch.setattr(cli, "AgenticCore", FakeCore)

    exit_code = cli.main(["--prompt", "hello"])
    captured = capsys.readouterr().out
    payload = json.loads(captured)

    assert exit_code == 1
    assert payload["status"] == "error"
    assert "missing config" in payload["errors"][0]
