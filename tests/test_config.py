from pathlib import Path

from agentic_core.config import load_agentic_config


def test_load_agentic_config_resolves_env_without_returning_secret(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.yml"
    config_path.write_text(
        """
provider:
  type: openai_compatible
  api_key_env: TEST_AGENT_KEY
  base_url_env: TEST_AGENT_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5
agent:
  system_prompt: System text
  max_turns: 4
  temperature: 0.1
  timeout_seconds: 30
tools:
  read_signals:
    enabled: true
paths:
  signals: data/signals/latest.json
  canonical_items: data/canonical-items/latest.json
  artifact_dir: data/agentic
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_AGENT_KEY", "secret-value")
    monkeypatch.setenv("TEST_AGENT_BASE_URL", "https://example.test/v1")

    config = load_agentic_config(config_path)

    assert config.provider.type == "openai_compatible"
    assert config.provider.api_key == "secret-value"
    assert config.provider.base_url == "https://example.test/v1"
    assert config.provider.safe_dict()["api_key_configured"] is True
    assert "secret-value" not in str(config.provider.safe_dict())
    assert config.agent.max_turns == 4
    assert config.tools["read_signals"].enabled is True
    assert config.paths.signals == Path("data/signals/latest.json")
