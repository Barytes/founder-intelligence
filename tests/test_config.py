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
    assert "secret-value" not in repr(config.provider)
    assert "secret-value" not in str(config.provider)
    assert "secret-value" not in str(config.provider.model_dump())
    assert "secret-value" not in str(config.provider.safe_dict())
    assert config.agent.max_turns == 4
    assert config.tools["read_signals"].enabled is True
    assert config.paths.signals == Path("data/signals/latest.json")


def test_load_agentic_config_applies_local_overrides(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.yml"
    local_config_path = tmp_path / "agent.local.yml"
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
    local_config_path.write_text(
        """
provider:
  model: gpt-4.1
agent:
  temperature: 0.3
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEST_AGENT_KEY", raising=False)
    monkeypatch.delenv("TEST_AGENT_BASE_URL", raising=False)

    config = load_agentic_config(config_path, local_config_path=local_config_path)

    assert config.provider.model == "gpt-4.1"
    assert config.provider.base_url == "https://api.openai.com/v1"
    assert config.agent.system_prompt == "System text"
    assert config.agent.temperature == 0.3
    assert config.tools["read_signals"].enabled is True


def test_load_agentic_config_uses_active_provider_profile(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.yml"
    local_config_path = tmp_path / "agent.local.yml"
    config_path.write_text(
        """
provider:
  type: openai_compatible
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_COMPATIBLE_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5
provider_profiles:
  active: openai
  items:
    openai:
      label: OpenAI
      type: openai_compatible
      api_key_env: OPENAI_API_KEY
      base_url: https://api.openai.com/v1
      model: gpt-5
    deepseek:
      label: DeepSeek
      type: openai_compatible
      api_key_env: DEEPSEEK_API_KEY
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat
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
    local_config_path.write_text(
        """
provider_profiles:
  active: deepseek
  items:
    deepseek:
      model: deepseek-reasoner
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")

    config = load_agentic_config(config_path, local_config_path=local_config_path)

    assert config.provider.api_key_env == "DEEPSEEK_API_KEY"
    assert config.provider.api_key == "deepseek-secret"
    assert config.provider.base_url == "https://api.deepseek.com/v1"
    assert config.provider.model == "deepseek-reasoner"


def test_load_agentic_config_maps_legacy_local_provider_model_to_active_profile(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "agent.yml"
    local_config_path = tmp_path / "agent.local.yml"
    config_path.write_text(
        """
provider:
  type: openai_compatible
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_COMPATIBLE_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5
provider_profiles:
  active: openai
  items:
    openai:
      label: OpenAI
      type: openai_compatible
      api_key_env: OPENAI_API_KEY
      base_url: https://api.openai.com/v1
      model: gpt-5
agent:
  system_prompt: System text
  max_turns: 4
  temperature: 0.1
  timeout_seconds: 30
paths:
  signals: data/signals/latest.json
  canonical_items: data/canonical-items/latest.json
  artifact_dir: data/agentic
""",
        encoding="utf-8",
    )
    local_config_path.write_text(
        """
provider:
  model: gpt-4.1
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)

    config = load_agentic_config(config_path, local_config_path=local_config_path)

    assert config.provider.model == "gpt-4.1"


def test_load_agentic_config_loads_custom_local_provider_profile(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "agent.yml"
    local_config_path = tmp_path / "agent.local.yml"
    config_path.write_text(
        """
provider:
  type: openai_compatible
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_COMPATIBLE_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5
provider_profiles:
  active: openai
  items:
    openai:
      label: OpenAI
      type: openai_compatible
      api_key_env: OPENAI_API_KEY
      base_url: https://api.openai.com/v1
      model: gpt-5
    custom:
      label: Custom
      type: openai_compatible
      api_key_env: CUSTOM_LLM_API_KEY
      base_url: https://api.openai.com/v1
      model: gpt-5
agent:
  system_prompt: System text
  max_turns: 4
  temperature: 0.1
  timeout_seconds: 30
paths:
  signals: data/signals/latest.json
  canonical_items: data/canonical-items/latest.json
  artifact_dir: data/agentic
""",
        encoding="utf-8",
    )
    local_config_path.write_text(
        """
provider_profiles:
  active: moonshot_ai
  items:
    moonshot_ai:
      label: Moonshot AI
      type: openai_compatible
      api_key_env: MOONSHOT_AI_LLM_API_KEY
      base_url: https://api.moonshot.cn/v1
      model: moonshot-v1-8k
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOONSHOT_AI_LLM_API_KEY", "moonshot-secret")

    config = load_agentic_config(config_path, local_config_path=local_config_path)

    assert config.provider.api_key_env == "MOONSHOT_AI_LLM_API_KEY"
    assert config.provider.api_key == "moonshot-secret"
    assert config.provider.base_url == "https://api.moonshot.cn/v1"
    assert config.provider.model == "moonshot-v1-8k"
