from datetime import datetime, timezone

from fastapi.testclient import TestClient
from pydantic_ai import ModelResponse, ToolCallPart, models
from pydantic_ai.models.function import FunctionModel

from agentic_core.feature_flags import L4FeatureFlags
from agentic_core.l4.agents.profile_compiler import (
    ProfileCompiler,
    ProfileCompilerOutput,
    ProfileService,
)
from agentic_core.l4.database import Database
from agentic_core.l4.domain import ProfileField
from agentic_core.l4.repositories import ContextEventRepository, ProfileRepository
from agentic_core.runtime.pydantic_ai_runtime import PydanticAIRuntime
from agentic_core.schemas import AgentConfig, AgenticConfig, PathConfig, ProviderConfig
from agentic_core.tools.registry import ToolRegistry
from web_workbench.app import create_app


models.ALLOW_MODEL_REQUESTS = False
ORIGIN = "http://testserver"
NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def config():
    return AgenticConfig(
        provider=ProviderConfig(
            type="openai_compatible",
            api_key_env="TEST",
            api_key="secret",
            base_url="https://example.test/v1",
            model="fixture-model",
        ),
        agent=AgentConfig(system_prompt="profile"),
        paths=PathConfig(),
    )


def output(event_id="event-1", value=None):
    return ProfileCompilerOutput(
        fields={
            "interests": ProfileField(
                value=value or ["reliability"],
                provenance_event_ids=(event_id,),
                confidence=1,
            )
        },
        change_summary="compiled",
    )


def app_with_profile_model(tmp_path, current_output, *, fail=False, enabled=True):
    database = Database(":memory:")
    events = ContextEventRepository(database)
    profiles = ProfileRepository(database)

    def model(_messages, info):
        if fail:
            raise TimeoutError("profile model timeout")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    current_output.model_dump(mode="json"),
                )
            ]
        )

    runtime = PydanticAIRuntime(
        config=config(), tools=ToolRegistry(), model=FunctionModel(model)
    )
    compiler = ProfileCompiler(
        repository=profiles,
        runtime=runtime,
        model_id="fixture-model",
        clock=lambda: NOW,
    )
    service = ProfileService(events=events, profiles=profiles, compiler=compiler)
    app = create_app(
        repo_root=tmp_path,
        auto_start_rsshub=False,
        l4_database=database,
        profile_service=service,
        l4_feature_flags=L4FeatureFlags(profile_enabled=enabled),
    )
    return app, database, service


def event_payload(event_id="event-1", event_type="user_statement", payload=None):
    return {
        "user_id": "user-1",
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload or {"text": "I care about reliability"},
        "origin": "test",
        "occurred_at": NOW.isoformat(),
    }


def test_context_event_api_compiles_profile_and_exposes_history(tmp_path):
    app, database, _service = app_with_profile_model(tmp_path, output())
    client = TestClient(app)

    created = client.post(
        "/api/context/events",
        headers={"origin": ORIGIN},
        json=event_payload(),
    )
    events = client.get("/api/context/events", params={"user_id": "user-1"})
    current = client.get("/api/profile/current", params={"user_id": "user-1"})
    history = client.get("/api/profile/history", params={"user_id": "user-1"})

    assert created.status_code == 200
    assert created.json()["status"] == "compiled"
    assert created.json()["profile_audit"]["changed_fields"] == ["interests"]
    assert [event["event_id"] for event in events.json()["events"]] == ["event-1"]
    assert current.json()["profile_status"] == "active"
    assert current.json()["effective_profile"]["fields"] == {
        "interests": ["reliability"]
    }
    assert len(history.json()["profiles"]) == 1
    database.close()


def test_profile_flag_off_persists_event_without_compiling_or_reading_defaults(tmp_path):
    app, database, _service = app_with_profile_model(
        tmp_path, output(), enabled=False
    )
    client = TestClient(app)

    response = client.post(
        "/api/context/events",
        headers={"origin": ORIGIN},
        json=event_payload(),
    )
    current = client.get("/api/profile/current", params={"user_id": "user-1"})

    assert response.json()["profile_status"] == "disabled"
    assert current.json()["profile_status"] == "uninitialized"
    assert current.json()["effective_profile"]["fields"] == {}
    database.close()


def test_passive_event_is_rejected_and_not_persisted(tmp_path):
    app, database, _service = app_with_profile_model(tmp_path, output())
    client = TestClient(app)

    response = client.post(
        "/api/context/events",
        headers={"origin": ORIGIN},
        json=event_payload(event_type="passive_behavior"),
    )

    assert response.status_code == 400
    assert client.get(
        "/api/context/events", params={"user_id": "user-1"}
    ).json()["events"] == []
    database.close()


def test_compile_failure_keeps_event_and_previous_active_profile(tmp_path):
    app, database, service = app_with_profile_model(tmp_path, output())
    client = TestClient(app)
    first = client.post(
        "/api/context/events",
        headers={"origin": ORIGIN},
        json=event_payload(),
    ).json()["profile"]

    def fail(_messages, _info):
        raise TimeoutError("profile model timeout")

    service.compiler.runtime = PydanticAIRuntime(
        config=config(), tools=ToolRegistry(), model=FunctionModel(fail)
    )
    failed = client.post(
        "/api/context/events",
        headers={"origin": ORIGIN},
        json=event_payload("event-2"),
    )

    assert failed.status_code == 200
    assert failed.json()["status"] == "accepted_degraded"
    assert failed.json()["profile"]["profile_id"] == first["profile_id"]
    assert "profile model timeout" in failed.json()["errors"][0]
    assert len(client.get(
        "/api/context/events", params={"user_id": "user-1"}
    ).json()["events"]) == 2
    database.close()


def test_context_event_requires_same_origin_and_forbids_extra_fields(tmp_path):
    app, database, _service = app_with_profile_model(tmp_path, output())
    client = TestClient(app)

    missing_origin = client.post("/api/context/events", json=event_payload())
    invalid = event_payload()
    invalid["unexpected"] = True
    extra = client.post(
        "/api/context/events",
        headers={"origin": ORIGIN},
        json=invalid,
    )

    assert missing_origin.status_code == 403
    assert extra.status_code == 422
    database.close()
