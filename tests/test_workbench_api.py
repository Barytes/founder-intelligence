from fastapi.testclient import TestClient

import web_workbench.app as workbench_app
from web_workbench.app import app
from agentic_core.schemas import RunResult


ORIGIN = "http://testserver"


def test_health_endpoint():
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_config_endpoint_hides_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    client = TestClient(app)

    response = client.get("/api/default-config")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"]["api_key_configured"] is True
    assert "secret" not in str(data)


def test_workbench_provider_has_single_base_url_input():
    html = (workbench_app.STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'href="/settings"' in html
    assert 'id="config-select"' not in html
    assert 'id="config-name-input"' not in html
    assert 'id="provider-select"' not in html
    assert 'id="base-url-input"' not in html
    assert 'id="base-url-edit-input"' not in html


def test_settings_page_contains_provider_and_github_token_forms():
    html = (workbench_app.STATIC_DIR / "settings.html").read_text(encoding="utf-8")

    assert 'href="/"' in html
    assert 'href="/agent"' in html
    assert 'id="provider-form"' in html
    assert 'id="github-token-form"' in html
    assert 'id="github-token-input"' in html


def test_settings_route_serves_settings_page():
    client = TestClient(workbench_app.app)

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Agent Settings" in response.text


def test_env_settings_reports_github_token_status_without_secret(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("GITHUB_ACCESS_TOKEN=ghp_supersecret\n", encoding="utf-8")
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.setenv("GITHUB_ACCESS_TOKEN", "ghp_supersecret")
    client = TestClient(workbench_app.app)

    response = client.get("/api/settings/env")

    assert response.status_code == 200
    data = response.json()
    assert data["github_token"]["configured"] is True
    assert data["github_token"]["env_key"] == "GITHUB_ACCESS_TOKEN"
    assert data["github_token"]["preview"] == "ghp_...cret"
    assert "ghp_supersecret" not in str(data)


def test_env_settings_saves_github_token_to_env_without_leaking_secret(
    monkeypatch, tmp_path
):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER_VAR=keep\nGITHUB_ACCESS_TOKEN=old\n", encoding="utf-8")
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.delenv("GITHUB_ACCESS_TOKEN", raising=False)
    client = TestClient(workbench_app.app)

    response = client.put(
        "/api/settings/env",
        headers={"origin": "http://testserver"},
        json={"github_token": "ghp_newsecret"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "saved"
    assert data["github_token"]["configured"] is True
    assert "ghp_newsecret" not in str(data)
    content = env_path.read_text(encoding="utf-8")
    assert "OTHER_VAR=keep" in content
    assert "GITHUB_ACCESS_TOKEN=ghp_newsecret" in content
    assert "GITHUB_ACCESS_TOKEN=old" not in content
    assert "ghp_newsecret" == workbench_app.os.environ["GITHUB_ACCESS_TOKEN"]


def test_env_settings_rejects_cross_origin_update(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "ENV_PATH", tmp_path / ".env")
    client = TestClient(workbench_app.app)

    response = client.put(
        "/api/settings/env",
        headers={"origin": "http://evil.example"},
        json={"github_token": "ghp_newsecret"},
    )

    assert response.status_code == 403
    assert not (tmp_path / ".env").exists()


def test_provider_settings_saves_api_key_to_env_without_leaking_secret(
    monkeypatch, tmp_path
):
    env_path = tmp_path / ".env"
    local_config_path = tmp_path / "agentic-core.local.yml"
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", local_config_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={
            "api_key": "sk-test-secret",
            "base_url": "https://example.test/v1",
            "model": "gpt-4.1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"]["api_key_configured"] is True
    assert "sk-test-secret" not in str(data)
    assert "OPENAI_API_KEY=sk-test-secret" in env_path.read_text(encoding="utf-8")
    assert "OPENAI_COMPATIBLE_BASE_URL=https://example.test/v1" not in env_path.read_text(
        encoding="utf-8"
    )
    assert "model: gpt-4.1" in local_config_path.read_text(encoding="utf-8")
    assert "base_url: https://example.test/v1" in local_config_path.read_text(
        encoding="utf-8"
    )
    assert data["provider"]["model"] == "gpt-4.1"
    assert "sk-test-secret" not in str(client.get("/api/default-config").json())


def test_provider_settings_rejects_cross_origin_update(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", tmp_path / "agentic-core.local.yml")
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": "http://evil.example"},
        json={"api_key": "sk-test-secret"},
    )

    assert response.status_code == 403
    assert not (tmp_path / ".env").exists()


def test_provider_settings_saves_profile_specific_key_and_model(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    local_config_path = tmp_path / "agentic-core.local.yml"
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", local_config_path)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={
            "provider_id": "deepseek",
            "api_key": "deepseek-secret",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert data["provider"]["api_key_configured"] is True
    assert data["provider"]["model"] == "deepseek-chat"
    env_content = env_path.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=deepseek-secret" in env_content
    assert "OPENAI_API_KEY=deepseek-secret" not in env_content
    local_content = local_config_path.read_text(encoding="utf-8")
    assert "active: deepseek" in local_content
    assert "deepseek:" in local_content
    assert "model: deepseek-chat" in local_content
    assert "base_url: https://api.deepseek.com/v1" in local_content
    assert "deepseek-secret" not in str(data)


def test_provider_settings_creates_named_custom_provider(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    local_config_path = tmp_path / "agentic-core.local.yml"
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", local_config_path)
    monkeypatch.delenv("MOONSHOT_AI_LLM_API_KEY", raising=False)
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={
            "provider_id": "custom",
            "config_name": "Moonshot AI",
            "api_key": "moonshot-secret",
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"]["api_key_env"] == "MOONSHOT_AI_LLM_API_KEY"
    assert data["provider"]["api_key_configured"] is True
    assert data["provider"]["model"] == "moonshot-v1-8k"
    assert "MOONSHOT_AI_LLM_API_KEY=moonshot-secret" in env_path.read_text(
        encoding="utf-8"
    )
    local_content = local_config_path.read_text(encoding="utf-8")
    assert "active: moonshot_ai" in local_content
    assert "moonshot_ai:" in local_content
    assert "label: Moonshot AI" in local_content
    assert "template: custom" in local_content
    assert "api_key_env: MOONSHOT_AI_LLM_API_KEY" in local_content
    assert "base_url: https://api.moonshot.cn/v1" in local_content
    assert "model: moonshot-v1-8k" in local_content
    assert "moonshot_ai" in data["provider_profiles"]["items"]
    assert data["provider_profiles"]["items"]["moonshot_ai"]["label"] == "Moonshot AI"
    assert "moonshot_ai" in data["saved_configs"]["items"]
    assert data["saved_configs"]["items"]["moonshot_ai"]["label"] == "Moonshot AI"
    assert "moonshot-secret" not in str(data)


def test_provider_settings_creates_named_config_from_provider_template(
    monkeypatch, tmp_path
):
    env_path = tmp_path / ".env"
    local_config_path = tmp_path / "agentic-core.local.yml"
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", local_config_path)
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={
            "provider_id": "deepseek",
            "config_name": "Work DeepSeek",
            "api_key": "work-secret",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"]["api_key_env"] == "WORK_DEEPSEEK_LLM_API_KEY"
    assert "WORK_DEEPSEEK_LLM_API_KEY=work-secret" in env_path.read_text(
        encoding="utf-8"
    )
    local_content = local_config_path.read_text(encoding="utf-8")
    assert "active: work_deepseek" in local_content
    assert "work_deepseek:" in local_content
    assert "label: Work DeepSeek" in local_content
    assert "template: deepseek" in local_content
    assert "api_key_env: WORK_DEEPSEEK_LLM_API_KEY" in local_content
    assert data["saved_configs"]["active"] == "work_deepseek"
    assert data["saved_configs"]["items"]["work_deepseek"]["template"] == "deepseek"


def test_provider_settings_rejects_custom_provider_name_collision(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", tmp_path / "agentic-core.local.yml")
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={
            "provider_id": "custom",
            "config_name": "OpenAI",
            "api_key": "secret",
            "base_url": "https://example.test/v1",
            "model": "model",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert any("conflicts" in error.lower() for error in data["errors"])


def test_default_config_returns_provider_profiles_without_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", tmp_path / "agentic-core.local.yml")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    client = TestClient(workbench_app.app)

    response = client.get("/api/default-config")

    assert response.status_code == 200
    data = response.json()
    assert data["provider_profiles"]["active"]
    assert "openai" in data["provider_templates"]["items"]
    assert "custom" in data["provider_templates"]["items"]
    assert data["saved_configs"] == {"active": None, "items": {}}
    assert "openai" in data["provider_profiles"]["items"]
    assert "deepseek" in data["provider_profiles"]["items"]
    assert data["provider_profiles"]["items"]["openai"]["api_key_configured"] is True
    assert data["provider_profiles"]["items"]["deepseek"]["api_key_configured"] is True
    assert "openai-secret" not in str(data)
    assert "deepseek-secret" not in str(data)


def test_saved_configs_only_include_local_profiles(monkeypatch, tmp_path):
    local_config_path = tmp_path / "agentic-core.local.yml"
    local_config_path.write_text(
        "provider_profiles:\n"
        "  active: work_deepseek\n"
        "  items:\n"
        "    work_deepseek:\n"
        "      label: Work DeepSeek\n"
        "      template: deepseek\n"
        "      type: openai_compatible\n"
        "      api_key_env: WORK_DEEPSEEK_LLM_API_KEY\n"
        "      base_url: https://api.deepseek.com/v1\n"
        "      model: deepseek-chat\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", local_config_path)
    client = TestClient(workbench_app.app)

    response = client.get("/api/default-config")

    assert response.status_code == 200
    data = response.json()
    assert data["saved_configs"]["active"] == "work_deepseek"
    assert list(data["saved_configs"]["items"].keys()) == ["work_deepseek"]
    assert data["saved_configs"]["items"]["work_deepseek"]["label"] == "Work DeepSeek"
    assert "openai" in data["provider_templates"]["items"]
    assert "deepseek" in data["provider_templates"]["items"]
    assert "openai" not in data["saved_configs"]["items"]
    assert "deepseek" not in data["saved_configs"]["items"]


def test_provider_settings_preserves_existing_env_lines(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OTHER_VAR=keep\nOPENAI_API_KEY=old\n# local comment\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench_app, "ENV_PATH", env_path)
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", tmp_path / "agentic-core.local.yml")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={"api_key": "sk-new"},
    )

    assert response.status_code == 200
    content = env_path.read_text(encoding="utf-8")
    assert "OTHER_VAR=keep" in content
    assert "# local comment" in content
    assert "OPENAI_API_KEY=sk-new" in content
    assert "OPENAI_API_KEY=old" not in content


def test_provider_settings_preserves_existing_local_config(monkeypatch, tmp_path):
    local_config_path = tmp_path / "agentic-core.local.yml"
    local_config_path.write_text(
        "agent:\n  temperature: 0.4\nprovider:\n  model: old-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench_app, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(workbench_app, "LOCAL_CONFIG", local_config_path)
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={"model": "gpt-4.1-mini"},
    )

    assert response.status_code == 200
    content = local_config_path.read_text(encoding="utf-8")
    assert "temperature: 0.4" in content
    assert "model: gpt-4.1-mini" in content
    assert response.json()["provider"]["model"] == "gpt-4.1-mini"


def test_provider_settings_rejects_newline_values(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "ENV_PATH", tmp_path / ".env")
    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/provider-settings",
        headers={"origin": ORIGIN},
        json={"api_key": "sk-test\nSECRET"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert any("newline" in error.lower() for error in data["errors"])


def test_agent_root_missing_ui(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "STATIC_DIR", tmp_path / "static")
    client = TestClient(workbench_app.app)

    response = client.get("/agent")

    assert response.status_code == 200
    assert response.json() == {
        "status": "missing_ui",
        "message": "Workbench UI has not been built yet.",
    }


def test_chat_returns_fake_result(monkeypatch):
    lifecycle = {"closed": False}

    class FakeCore:
        @classmethod
        def from_config(cls, _config):
            return cls()

        def run(self, **_kwargs):
            return RunResult(status="ok", messages=[], final_text="fake response")

        def close(self):
            lifecycle["closed"] = True

    monkeypatch.setattr(workbench_app, "AgenticCore", FakeCore)

    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/chat",
        headers={"origin": ORIGIN},
        json={"message": "hi", "config_path": "config/agentic-core.example.yml"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "messages": [],
        "final_text": "fake response",
        "tool_calls": [],
        "artifact_paths": [],
        "usage": {},
        "errors": [],
    }
    assert lifecycle["closed"] is True


def test_chat_closes_core_when_run_fails(monkeypatch):
    lifecycle = {"closed": False}

    class FakeCore:
        @classmethod
        def from_config(cls, _config):
            return cls()

        def run(self, **_kwargs):
            raise RuntimeError("model failed")

        def close(self):
            lifecycle["closed"] = True

    monkeypatch.setattr(workbench_app, "AgenticCore", FakeCore)

    response = TestClient(workbench_app.app).post(
        "/api/chat",
        headers={"origin": ORIGIN},
        json={"message": "hi", "config_path": "config/agentic-core.example.yml"},
    )

    assert response.status_code == 200
    assert response.json()["errors"] == ["model failed"]
    assert lifecycle["closed"] is True


def test_chat_config_path_outside_repo_error():
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={"origin": ORIGIN},
        json={"message": "hi", "config_path": "../../etc/passwd"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert any("outside repository" in err.lower() for err in data["errors"])


def test_chat_non_yaml_config_error():
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={"origin": ORIGIN},
        json={"message": "hi", "config_path": "config/agentic-core.example.txt"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert any("yaml" in err.lower() for err in data["errors"])


def test_chat_from_config_error_is_returned_as_runresult(monkeypatch):
    class FakeCore:
        @classmethod
        def from_config(cls, _config):
            raise FileNotFoundError("missing config")

    monkeypatch.setattr(workbench_app, "AgenticCore", FakeCore)

    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/chat",
        headers={"origin": ORIGIN},
        json={"message": "hi", "config_path": "config/agentic-core.example.yml"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert any("missing config" in err for err in data["errors"])
    assert data["messages"] == []
    assert data["final_text"] == ""
