import json

from fastapi.testclient import TestClient

from web_workbench.app import create_app, ensure_rsshub


ORIGIN = "http://127.0.0.1:4567"


class FakeRunner:
    def __init__(self):
        self.calls = 0

    def refresh(self):
        self.calls += 1
        return {"status": "started"}


def test_dashboard_and_agent_pages_are_served_by_one_fastapi_app(tmp_path):
    write_repo_fixture(tmp_path)
    client = TestClient(create_app(repo_root=tmp_path, runner=FakeRunner()))

    dashboard = client.get("/")
    agent = client.get("/agent")

    assert dashboard.status_code == 200
    assert "信号控制台" in dashboard.text
    assert 'href="/agent"' in dashboard.text
    assert agent.status_code == 200
    assert "Agentic Core" in agent.text
    assert 'href="/"' in agent.text
    assert "/agent/static/app.js" in agent.text


def test_dashboard_apis_preserve_existing_web_app_contract(tmp_path):
    write_repo_fixture(tmp_path)
    client = TestClient(create_app(repo_root=tmp_path, runner=FakeRunner()))

    signals = client.get("/api/signals/latest")
    sources = client.get("/api/sources")
    profile = client.get("/api/profile")

    assert signals.status_code == 200
    assert signals.json()["input_run_id"] == "run-api"
    assert sources.status_code == 200
    github = next(
        source for source in sources.json()["sources"] if source["id"] == "github-trending-daily"
    )
    assert github["enabled"] is True
    assert github["runnable"] is True
    assert profile.status_code == 200
    assert profile.json()["path"] == "config/user-profile.yml"
    assert "Founder Intelligence User" in profile.json()["content"]


def test_dashboard_profile_and_sources_can_be_written_with_same_origin(tmp_path):
    write_repo_fixture(tmp_path)
    client = TestClient(create_app(repo_root=tmp_path, runner=FakeRunner(), allowed_origins=[ORIGIN]))

    updated_profile = sample_profile_yaml().replace("Founder Intelligence User", "Updated User")
    profile_response = client.put(
        "/api/profile",
        headers={"origin": ORIGIN},
        json={"content": updated_profile},
    )
    assert profile_response.status_code == 200
    assert "Updated User" in (tmp_path / "config/user-profile.yml").read_text(encoding="utf-8")

    toggle_response = client.post(
        "/api/sources/github-trending-daily",
        headers={"origin": ORIGIN},
        json={"enabled": False},
    )
    assert toggle_response.status_code == 200
    assert toggle_response.json()["source"]["runnable"] is False
    assert "enabled: false" in (tmp_path / "config/sources.yml").read_text(encoding="utf-8")


def test_refresh_enforces_same_origin_and_rejects_command_parameters(tmp_path):
    write_repo_fixture(tmp_path)
    runner = FakeRunner()
    client = TestClient(create_app(repo_root=tmp_path, runner=runner, allowed_origins=[ORIGIN]))

    forbidden = client.post("/api/refresh", headers={"origin": "http://evil.example"}, json={})
    command = client.post("/api/refresh", headers={"origin": ORIGIN}, json={"command": "whoami"})
    accepted = client.post("/api/refresh", headers={"origin": ORIGIN}, json={})

    assert forbidden.status_code == 403
    assert command.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "started"
    assert runner.calls == 1


def test_refresh_accepts_current_request_origin_on_non_default_port(tmp_path):
    write_repo_fixture(tmp_path)
    runner = FakeRunner()
    client = TestClient(
        create_app(repo_root=tmp_path, runner=runner),
        base_url="http://127.0.0.1:4568",
    )

    response = client.post(
        "/api/refresh",
        headers={"origin": "http://127.0.0.1:4568"},
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert runner.calls == 1


def test_ensure_rsshub_invokes_docker_compose_when_enabled(tmp_path):
    compose_file = tmp_path / "config/docker-compose.yml"
    compose_file.parent.mkdir(parents=True)
    compose_file.write_text("services:\n  rsshub:\n    image: diygod/rsshub\n", encoding="utf-8")
    calls = []

    result = ensure_rsshub(tmp_path, run_command=lambda argv: calls.append(argv))

    assert (tmp_path / ".env").read_text(encoding="utf-8") == ""
    assert result == {
        "status": "started",
        "command": ["docker", "compose", "-f", str(compose_file), "up", "-d", "rsshub"],
    }
    assert calls == [["docker", "compose", "-f", str(compose_file), "up", "-d", "rsshub"]]


def test_workbench_auto_starts_rsshub_by_default(monkeypatch, tmp_path):
    starts = []

    def fake_ensure_rsshub(root):
        starts.append(root)
        return {"status": "started"}

    monkeypatch.delenv("FI_AUTO_START_RSSHUB", raising=False)
    monkeypatch.setattr("web_workbench.app.ensure_rsshub", fake_ensure_rsshub)
    write_repo_fixture(tmp_path)

    with TestClient(create_app(repo_root=tmp_path, runner=FakeRunner())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert starts == [tmp_path]


def test_workbench_can_disable_rsshub_auto_start_with_env(monkeypatch, tmp_path):
    starts = []

    def fake_ensure_rsshub(root):
        starts.append(root)
        return {"status": "started"}

    monkeypatch.setenv("FI_AUTO_START_RSSHUB", "0")
    monkeypatch.setattr("web_workbench.app.ensure_rsshub", fake_ensure_rsshub)
    write_repo_fixture(tmp_path)

    with TestClient(create_app(repo_root=tmp_path, runner=FakeRunner())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert starts == []


def write_repo_fixture(root):
    write(root, "config/user-profile.yml", sample_profile_yaml())
    write(root, "config/sources.yml", sample_sources_yaml())
    write_json(root, "data/signals/latest.json", sample_signal_output())


def write(root, path, content):
    full_path = root / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")


def write_json(root, path, value):
    write(root, path, json.dumps(value, indent=2) + "\n")


def sample_profile_yaml():
    return """\
version: 1
user:
  name: Founder Intelligence User
interests:
  - AI coding
output_preferences:
  default_top_n: 10
"""


def sample_sources_yaml():
    return """\
version: 1
sources:
  - id: github-trending-daily
    name: GitHub Trending Daily
    source_type: rss
    provider: github
    fetcher: rsshub
    enabled: true
    priority: high
    category: developer_trends
    connection:
      rss_url: http://localhost:1200/github/trending/daily/any
    schedule:
      refresh_interval_minutes: 30
    tags:
      - open-source
  - id: disabled-source
    name: Disabled Source
    source_type: rss
    provider: example
    fetcher: rsshub
    enabled: false
    category: reference_feed
    connection:
      rss_url: http://localhost:1200/example
source_templates:
  future_mcp:
    source_type: mcp
    provider: future
    enabled: false
    category: future
"""


def sample_signal_output():
    return {
        "contract_version": 1,
        "generated_at": "2026-07-08T10:00:00+08:00",
        "input_run_id": "run-api",
        "summary": {"input_items": 2, "signals": 1, "top_n": 10},
        "signals": [
            {
                "id": "signal-api",
                "title": "API Signal",
                "source": {"name": "GitHub Trending", "provider": "github", "type": "rss"},
                "what_happened": "Signal rendered from API.",
                "total_score": 4.5,
                "importance_score": 5,
                "relevance_score": 4,
                "tags": ["rss"],
            }
        ],
    }
