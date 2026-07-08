from fastapi.testclient import TestClient

from web_workbench.app import app


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
