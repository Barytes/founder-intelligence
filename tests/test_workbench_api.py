from fastapi.testclient import TestClient

import web_workbench.app as workbench_app
from web_workbench.app import app
from agentic_core.schemas import RunResult


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


def test_root_missing_ui(monkeypatch, tmp_path):
    monkeypatch.setattr(workbench_app, "STATIC_DIR", tmp_path / "static")
    client = TestClient(workbench_app.app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "missing_ui",
        "message": "Workbench UI has not been built yet.",
    }


def test_chat_returns_fake_result(monkeypatch):
    class FakeCore:
        @classmethod
        def from_config(cls, _config):
            return cls()

        def run(self, **_kwargs):
            return RunResult(status="ok", messages=[], final_text="fake response")

    monkeypatch.setattr(workbench_app, "AgenticCore", FakeCore)

    client = TestClient(workbench_app.app)

    response = client.post(
        "/api/chat",
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


def test_chat_config_path_outside_repo_error():
    client = TestClient(app)

    response = client.post(
        "/api/chat",
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
        json={"message": "hi", "config_path": "config/agentic-core.example.yml"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert any("missing config" in err for err in data["errors"])
    assert data["messages"] == []
    assert data["final_text"] == ""
