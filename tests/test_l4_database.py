from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from agentic_core.l4.database import (
    DEFAULT_MIGRATIONS,
    Database,
    DatabaseCorruptionError,
    Migration,
    MigrationError,
)
from agentic_core.l4.domain import (
    AcquisitionBinding,
    BindingStatus,
    ConnectorType,
    ContextEventType,
    Explicitness,
    ProfileField,
    ProfileSnapshot,
    SourceKind,
    SourceStatus,
    SourceTarget,
    StepStatus,
    UserContextEvent,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepTrace,
)
from agentic_core.l4.hashing import canonical_hash, profile_snapshot_hash, source_identity_key
from agentic_core.l4.repositories import (
    ContextEventRepository,
    IdempotencyConflictError,
    ProfileRepository,
    RepositoryError,
    SourceRepository,
    WorkflowRepository,
)


NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def make_event(event_id: str = "event-1", text: str = "Explicit goal"):
    return UserContextEvent(
        event_id=event_id,
        user_id="user-1",
        event_type=ContextEventType.USER_STATEMENT,
        payload={"text": text},
        origin="test",
        explicitness=Explicitness.EXPLICIT,
        occurred_at=NOW,
        recorded_at=NOW,
        idempotency_key=f"context:v1:{event_id}",
    )


def make_profile(
    profile_id: str = "profile-1",
    event_id: str = "event-1",
    *,
    inferred_expiry=None,
):
    draft = ProfileSnapshot(
        profile_id=profile_id,
        user_id="user-1",
        based_on_event_ids=(event_id,),
        fields={
            "interest": ProfileField(
                value=profile_id,
                provenance_event_ids=(event_id,),
                confidence=1 if inferred_expiry is None else 0.6,
                inferred=inferred_expiry is not None,
                expires_at=inferred_expiry,
            )
        },
        created_at=NOW + timedelta(minutes=int(profile_id[-1])),
        model_id="fixture",
        prompt_version="profile-v1",
        policy_version="policy-v1",
        profile_hash="pending",
    )
    return draft.model_copy(
        update={
            "profile_hash": profile_snapshot_hash(draft)
        }
    )


def test_database_initializes_file_with_required_pragmas_and_idempotent_migrations(tmp_path):
    path = tmp_path / "nested" / "app.db"
    database = Database(path)
    database.apply_migrations(DEFAULT_MIGRATIONS)

    assert path.exists()
    assert database.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert database.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert database.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 5
    database.close()


def test_database_supports_in_memory_repositories():
    database = Database(":memory:")
    repository = ContextEventRepository(database)

    assert repository.append(make_event()) == make_event()
    assert repository.get("event-1") == make_event()
    database.close()


def test_corrupt_database_fails_without_replacing_file(tmp_path):
    path = tmp_path / "corrupt.db"
    original = b"this is not sqlite"
    path.write_bytes(original)

    with pytest.raises(DatabaseCorruptionError, match="not replaced"):
        Database(path)

    assert path.read_bytes() == original


def test_failed_migration_rolls_back_its_schema_and_version():
    database = Database(":memory:", auto_migrate=False)
    database.apply_migrations(DEFAULT_MIGRATIONS)

    def fail(connection):
        connection.execute("CREATE TABLE should_rollback(value TEXT)")
        connection.execute("INSERT INTO missing_table VALUES (1)")

    with pytest.raises(MigrationError, match="rolled back"):
        database.apply_migrations((Migration(6, fail),))

    assert database.execute(
        "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
    ).fetchone() is None
    assert database.execute(
        "SELECT version FROM schema_migrations WHERE version = 6"
    ).fetchone() is None


def test_context_event_is_idempotent_but_conflicting_duplicate_fails():
    database = Database(":memory:")
    repository = ContextEventRepository(database)

    first = repository.append(make_event())
    repeated = repository.append(make_event())
    conflict = make_event(text="Different content")

    assert repeated == first
    with pytest.raises(IdempotencyConflictError):
        repository.append(conflict)
    assert len(repository.list_for_user("user-1")) == 1


def test_append_only_tables_reject_update_and_delete():
    database = Database(":memory:")
    ContextEventRepository(database).append(make_event())

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        database.execute(
            "UPDATE context_events SET user_id = 'attacker' WHERE event_id = 'event-1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        database.execute("DELETE FROM context_events WHERE event_id = 'event-1'")


def test_profile_snapshot_and_active_pointer_switch_atomically():
    database = Database(":memory:")
    events = ContextEventRepository(database)
    profiles = ProfileRepository(database)
    events.append(make_event())
    first = make_profile()
    profiles.save_and_activate(first)

    events.append(make_event("event-2"))
    second = make_profile("profile-2", "event-2")
    profiles.save_and_activate(second)

    assert profiles.get_active("user-1") == second
    assert profiles.history("user-1") == [first, second]
    assert profiles.rollback("user-1", "profile-1") == first
    assert profiles.get_active("user-1") == first


def test_profile_activation_failure_leaves_no_half_snapshot():
    database = Database(":memory:")
    ContextEventRepository(database).append(make_event())
    profiles = ProfileRepository(database)
    profiles._before_activate = lambda _snapshot: (_ for _ in ()).throw(
        RuntimeError("injected activation failure")
    )

    with pytest.raises(RuntimeError, match="injected"):
        profiles.save_and_activate(make_profile())

    assert profiles.get("profile-1") is None
    assert profiles.get_active("user-1") is None


def test_profile_rejects_missing_provenance_and_resolves_neutral_or_ttl():
    database = Database(":memory:")
    profiles = ProfileRepository(database)
    assert profiles.resolve_effective_profile("user-1").initialized is False

    with pytest.raises(RepositoryError, match="missing context event"):
        profiles.save_and_activate(make_profile())

    ContextEventRepository(database).append(make_event())
    snapshot = make_profile(inferred_expiry=NOW + timedelta(hours=1))
    profiles.save_and_activate(snapshot)
    effective = profiles.resolve_effective_profile(
        "user-1", at=NOW + timedelta(hours=2)
    )
    assert effective.initialized is True
    assert effective.fields == {}


def test_source_repository_tracks_history_and_builds_stable_snapshot():
    database = Database(":memory:")
    repository = SourceRepository(database)
    identity = source_identity_key(
        source_kind="creator", provider="bilibili", canonical_external_id="42"
    )
    target = SourceTarget(
        target_id="target-1",
        source_kind=SourceKind.CREATOR,
        provider="bilibili",
        canonical_external_id="42",
        canonical_url="https://space.bilibili.com/42",
        display_name="Creator",
        identity_key=identity,
        status=SourceStatus.PROBATION,
        created_at=NOW,
        updated_at=NOW,
    )
    config = {"route": "/bilibili/user/video/42"}
    binding = AcquisitionBinding(
        binding_id="binding-1",
        target_id="target-1",
        connector_type=ConnectorType.RSSHUB,
        config=config,
        config_hash=canonical_hash(config),
        status=BindingStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )

    assert repository.upsert_target(target) == target
    assert repository.upsert_target(target) == target
    repository.add_binding(binding)
    promoted = repository.set_target_status(
        "target-1", SourceStatus.ACTIVE, reason="validated"
    )
    unhealthy = repository.set_binding_status(
        "binding-1", BindingStatus.UNHEALTHY, reason="probe failed"
    )
    repository.set_binding_status(
        "binding-1", BindingStatus.ACTIVE, reason="probe recovered"
    )
    snapshot = repository.create_snapshot(snapshot_id="snapshot-1")
    repeated = repository.create_snapshot(snapshot_id="snapshot-2")

    assert promoted.status == SourceStatus.ACTIVE
    assert unhealthy.status == BindingStatus.UNHEALTHY
    assert len(repository.list_targets()) == 1
    assert len(repository.list_bindings()) == 1
    assert snapshot.sources[0].target.status == SourceStatus.ACTIVE
    assert repeated.snapshot_id == "snapshot-1"
    assert repeated.snapshot_hash == snapshot.snapshot_hash
    assert database.execute("SELECT COUNT(*) FROM source_target_history").fetchone()[0] == 2
    assert database.execute("SELECT COUNT(*) FROM binding_history").fetchone()[0] == 3


def test_workflow_trace_is_append_only_and_foreign_keyed():
    database = Database(":memory:")
    repository = WorkflowRepository(database)
    run = WorkflowRun(
        run_id="run-1",
        status=WorkflowStatus.RUNNING,
        started_at=NOW,
        input_hash="input",
    )
    repository.create_run(run)
    trace = WorkflowStepTrace(
        trace_id="trace-1",
        run_id="run-1",
        step_name="profile",
        sequence=1,
        status=StepStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW,
        input_hash="input",
        output_hash="output",
    )
    repository.append_trace(trace)

    assert repository.list_traces("run-1") == [trace]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        database.execute(
            "UPDATE workflow_step_traces SET status = 'failed' WHERE trace_id = 'trace-1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        repository.append_trace(trace.model_copy(update={"trace_id": "x", "run_id": "missing"}))


def test_l4_domain_and_repository_layer_has_no_web_or_agent_framework_dependency():
    root = Path(__file__).resolve().parents[1] / "src" / "agentic-core" / "agentic_core" / "l4"
    source = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("domain.py", "hashing.py", "database.py", "repositories.py")
    )

    assert "fastapi" not in source
    assert "pydantic_ai" not in source
