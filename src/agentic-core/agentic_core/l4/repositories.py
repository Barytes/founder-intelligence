from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import sqlite3
from typing import Any

from agentic_core.l4.database import Database
from agentic_core.l4.domain import (
    AcquisitionBinding,
    AgentAssessment,
    BindingStatus,
    EffectiveProfile,
    InboxItem,
    ProfileSnapshot,
    RankedSignal,
    ResolvedSource,
    ResolvedSourceSnapshot,
    SourceStatus,
    SourceTarget,
    UserContextEvent,
    WorkflowRun,
    WorkflowStepTrace,
)
from agentic_core.l4.hashing import canonical_hash, canonical_json, profile_snapshot_hash


class RepositoryError(RuntimeError):
    pass


class IdempotencyConflictError(RepositoryError):
    pass


class ImmutableConflictError(RepositoryError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload(model: Any) -> str:
    return canonical_json(model)


class ContextEventRepository:
    def __init__(self, database: Database):
        self.database = database

    def append(self, event: UserContextEvent) -> UserContextEvent:
        payload = _payload(event)
        content_hash = canonical_hash(event)
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT payload, content_hash FROM context_events WHERE idempotency_key = ? OR event_id = ?",
                (event.idempotency_key, event.event_id),
            ).fetchone()
            if existing:
                if existing["content_hash"] != content_hash:
                    raise IdempotencyConflictError(
                        "event id or idempotency key already exists with different content"
                    )
                return UserContextEvent.model_validate_json(existing["payload"])
            connection.execute(
                """
                INSERT INTO context_events(
                    event_id, user_id, event_type, occurred_at,
                    idempotency_key, payload, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.user_id,
                    event.event_type.value,
                    event.occurred_at.isoformat(),
                    event.idempotency_key,
                    payload,
                    content_hash,
                ),
            )
        return event

    def get(self, event_id: str) -> UserContextEvent | None:
        row = self.database.execute(
            "SELECT payload FROM context_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return UserContextEvent.model_validate_json(row["payload"]) if row else None

    def list_for_user(self, user_id: str) -> list[UserContextEvent]:
        rows = self.database.execute(
            """
            SELECT payload FROM context_events
            WHERE user_id = ? ORDER BY occurred_at, event_id
            """,
            (user_id,),
        ).fetchall()
        return [UserContextEvent.model_validate_json(row["payload"]) for row in rows]


class ProfileRepository:
    def __init__(self, database: Database):
        self.database = database
        self._before_activate: Callable[[ProfileSnapshot], None] = lambda _snapshot: None

    def save_and_activate(self, snapshot: ProfileSnapshot) -> ProfileSnapshot:
        expected_hash = profile_snapshot_hash(snapshot)
        if snapshot.profile_hash != expected_hash:
            raise RepositoryError("profile hash does not match snapshot content")
        saved_snapshot = snapshot
        with self.database.transaction() as connection:
            event_rows = connection.execute(
                "SELECT event_id, user_id FROM context_events WHERE event_id IN ({})".format(
                    ",".join("?" for _ in snapshot.based_on_event_ids) or "NULL"
                ),
                tuple(snapshot.based_on_event_ids),
            ).fetchall()
            event_ids = {row["event_id"] for row in event_rows}
            if event_ids != set(snapshot.based_on_event_ids):
                raise RepositoryError("profile references missing context event")
            if any(row["user_id"] != snapshot.user_id for row in event_rows):
                raise RepositoryError("profile references another user's event")

            existing = connection.execute(
                "SELECT payload FROM profile_snapshots WHERE profile_id = ? OR profile_hash = ?",
                (snapshot.profile_id, snapshot.profile_hash),
            ).fetchone()
            if existing:
                saved = ProfileSnapshot.model_validate_json(existing["payload"])
                if saved.profile_hash == snapshot.profile_hash:
                    saved_snapshot = saved
                elif saved != snapshot:
                    raise ImmutableConflictError("profile snapshot is immutable")
            else:
                connection.execute(
                    """
                    INSERT INTO profile_snapshots(
                        profile_id, user_id, created_at, profile_hash, payload
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.profile_id,
                        snapshot.user_id,
                        snapshot.created_at.isoformat(),
                        snapshot.profile_hash,
                        _payload(snapshot),
                    ),
                )
            self._before_activate(saved_snapshot)
            connection.execute(
                """
                INSERT INTO active_profiles(user_id, profile_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    updated_at = excluded.updated_at
                """,
                (saved_snapshot.user_id, saved_snapshot.profile_id, _now()),
            )
        return saved_snapshot

    def get(self, profile_id: str) -> ProfileSnapshot | None:
        row = self.database.execute(
            "SELECT payload FROM profile_snapshots WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        return ProfileSnapshot.model_validate_json(row["payload"]) if row else None

    def get_active(self, user_id: str) -> ProfileSnapshot | None:
        row = self.database.execute(
            """
            SELECT p.payload FROM active_profiles a
            JOIN profile_snapshots p ON p.profile_id = a.profile_id
            WHERE a.user_id = ?
            """,
            (user_id,),
        ).fetchone()
        return ProfileSnapshot.model_validate_json(row["payload"]) if row else None

    def history(self, user_id: str) -> list[ProfileSnapshot]:
        rows = self.database.execute(
            """
            SELECT payload FROM profile_snapshots
            WHERE user_id = ? ORDER BY created_at, profile_id
            """,
            (user_id,),
        ).fetchall()
        return [ProfileSnapshot.model_validate_json(row["payload"]) for row in rows]

    def rollback(self, user_id: str, profile_id: str) -> ProfileSnapshot:
        snapshot = self.get(profile_id)
        if snapshot is None or snapshot.user_id != user_id:
            raise RepositoryError("profile snapshot not found for user")
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO active_profiles(user_id, profile_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    updated_at = excluded.updated_at
                """,
                (user_id, profile_id, _now()),
            )
        return snapshot

    def resolve_effective_profile(
        self, user_id: str, *, at: datetime | None = None
    ) -> EffectiveProfile:
        snapshot = self.get_active(user_id)
        if snapshot is None:
            return EffectiveProfile(user_id=user_id, initialized=False)
        now = at or datetime.now(timezone.utc)
        fields = {
            name: field.value
            for name, field in snapshot.fields.items()
            if field.expires_at is None or field.expires_at > now
        }
        return EffectiveProfile(
            user_id=user_id,
            initialized=True,
            profile_id=snapshot.profile_id,
            profile_hash=snapshot.profile_hash,
            fields=fields,
        )


class SourceRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert_target(self, target: SourceTarget, *, reason: str = "created") -> SourceTarget:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM source_targets WHERE identity_key = ? OR target_id = ?",
                (target.identity_key, target.target_id),
            ).fetchone()
            if row:
                return SourceTarget.model_validate_json(row["payload"])
            connection.execute(
                """
                INSERT INTO source_targets(
                    target_id, identity_key, source_kind, provider,
                    canonical_external_id, canonical_url, status, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target.target_id,
                    target.identity_key,
                    target.source_kind.value,
                    target.provider,
                    target.canonical_external_id,
                    target.canonical_url,
                    target.status.value,
                    target.updated_at.isoformat(),
                    _payload(target),
                ),
            )
            self._append_target_history(connection, target, reason)
        return target

    def _append_target_history(
        self, connection: sqlite3.Connection, target: SourceTarget, reason: str
    ) -> None:
        connection.execute(
            """
            INSERT INTO source_target_history(target_id, status, changed_at, reason, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (target.target_id, target.status.value, _now(), reason, _payload(target)),
        )

    def get_target(self, target_id: str) -> SourceTarget | None:
        row = self.database.execute(
            "SELECT payload FROM source_targets WHERE target_id = ?", (target_id,)
        ).fetchone()
        return SourceTarget.model_validate_json(row["payload"]) if row else None

    def find_target_by_identity(self, identity_key: str) -> SourceTarget | None:
        row = self.database.execute(
            "SELECT payload FROM source_targets WHERE identity_key = ?",
            (identity_key,),
        ).fetchone()
        return SourceTarget.model_validate_json(row["payload"]) if row else None

    def replace_target_from_import(
        self, target: SourceTarget, *, reason: str
    ) -> SourceTarget:
        existing = self.find_target_by_identity(target.identity_key)
        if existing is None:
            return self.upsert_target(target, reason=reason)
        updated = target.model_copy(
            update={
                "target_id": existing.target_id,
                "created_at": existing.created_at,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        if updated == existing:
            return existing
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE source_targets SET
                    source_kind = ?, provider = ?, canonical_external_id = ?,
                    canonical_url = ?, status = ?, updated_at = ?, payload = ?
                WHERE target_id = ?
                """,
                (
                    updated.source_kind.value,
                    updated.provider,
                    updated.canonical_external_id,
                    updated.canonical_url,
                    updated.status.value,
                    updated.updated_at.isoformat(),
                    _payload(updated),
                    existing.target_id,
                ),
            )
            self._append_target_history(connection, updated, reason)
        return updated

    def list_targets(self) -> list[SourceTarget]:
        rows = self.database.execute(
            "SELECT payload FROM source_targets ORDER BY target_id"
        ).fetchall()
        return [SourceTarget.model_validate_json(row["payload"]) for row in rows]

    def set_target_status(
        self, target_id: str, status: SourceStatus, *, reason: str
    ) -> SourceTarget:
        existing = self.get_target(target_id)
        if existing is None:
            raise RepositoryError("source target not found")
        updated = existing.model_copy(
            update={"status": status, "updated_at": datetime.now(timezone.utc)}
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE source_targets SET status = ?, updated_at = ?, payload = ? WHERE target_id = ?",
                (
                    status.value,
                    updated.updated_at.isoformat(),
                    _payload(updated),
                    target_id,
                ),
            )
            self._append_target_history(connection, updated, reason)
        return updated

    def add_binding(
        self, binding: AcquisitionBinding, *, reason: str = "created"
    ) -> AcquisitionBinding:
        if self.get_target(binding.target_id) is None:
            raise RepositoryError("binding target does not exist")
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM acquisition_bindings
                WHERE binding_id = ? OR (target_id = ? AND connector_type = ? AND config_hash = ?)
                """,
                (
                    binding.binding_id,
                    binding.target_id,
                    binding.connector_type.value,
                    binding.config_hash,
                ),
            ).fetchone()
            if row:
                return AcquisitionBinding.model_validate_json(row["payload"])
            connection.execute(
                """
                INSERT INTO acquisition_bindings(
                    binding_id, target_id, connector_type, config_hash,
                    status, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.binding_id,
                    binding.target_id,
                    binding.connector_type.value,
                    binding.config_hash,
                    binding.status.value,
                    binding.updated_at.isoformat(),
                    _payload(binding),
                ),
            )
            connection.execute(
                """
                INSERT INTO binding_history(binding_id, status, changed_at, reason, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    binding.binding_id,
                    binding.status.value,
                    _now(),
                    reason,
                    _payload(binding),
                ),
            )
        return binding

    def list_bindings(self, target_id: str | None = None) -> list[AcquisitionBinding]:
        if target_id is None:
            rows = self.database.execute(
                "SELECT payload FROM acquisition_bindings ORDER BY binding_id"
            ).fetchall()
        else:
            rows = self.database.execute(
                "SELECT payload FROM acquisition_bindings WHERE target_id = ? ORDER BY binding_id",
                (target_id,),
            ).fetchall()
        return [AcquisitionBinding.model_validate_json(row["payload"]) for row in rows]

    def get_binding(self, binding_id: str) -> AcquisitionBinding | None:
        row = self.database.execute(
            "SELECT payload FROM acquisition_bindings WHERE binding_id = ?",
            (binding_id,),
        ).fetchone()
        return AcquisitionBinding.model_validate_json(row["payload"]) if row else None

    def set_binding_status(
        self, binding_id: str, status: BindingStatus, *, reason: str
    ) -> AcquisitionBinding:
        existing = self.get_binding(binding_id)
        if existing is None:
            raise RepositoryError("acquisition binding not found")
        updated = existing.model_copy(
            update={"status": status, "updated_at": datetime.now(timezone.utc)}
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE acquisition_bindings
                SET status = ?, updated_at = ?, payload = ?
                WHERE binding_id = ?
                """,
                (
                    status.value,
                    updated.updated_at.isoformat(),
                    _payload(updated),
                    binding_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO binding_history(binding_id, status, changed_at, reason, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (binding_id, status.value, _now(), reason, _payload(updated)),
            )
        return updated

    def create_snapshot(
        self, *, snapshot_id: str, workflow_run_id: str | None = None
    ) -> ResolvedSourceSnapshot:
        target_by_id = {
            target.target_id: target
            for target in self.list_targets()
            if target.status in {SourceStatus.ACTIVE, SourceStatus.PROBATION}
        }
        sources = tuple(sorted((
            ResolvedSource(target=target_by_id[binding.target_id], binding=binding)
            for binding in self.list_bindings()
            if binding.target_id in target_by_id and binding.status == BindingStatus.ACTIVE
        ), key=lambda source: (
            source.binding.config.get("import_order", 1_000_000),
            source.target.target_id,
            source.binding.binding_id,
        )))
        snapshot_hash = canonical_hash(
            [source.model_dump(mode="json") for source in sources]
        )
        snapshot = ResolvedSourceSnapshot(
            snapshot_id=snapshot_id,
            sources=sources,
            snapshot_hash=snapshot_hash,
            workflow_run_id=workflow_run_id,
        )
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT payload FROM source_snapshots WHERE snapshot_hash = ? OR snapshot_id = ?",
                (snapshot_hash, snapshot_id),
            ).fetchone()
            if existing:
                return ResolvedSourceSnapshot.model_validate_json(existing["payload"])
            connection.execute(
                """
                INSERT INTO source_snapshots(
                    snapshot_id, snapshot_hash, created_at, workflow_run_id, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.snapshot_hash,
                    snapshot.created_at.isoformat(),
                    workflow_run_id,
                    _payload(snapshot),
                ),
            )
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> ResolvedSourceSnapshot | None:
        row = self.database.execute(
            "SELECT payload FROM source_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        return ResolvedSourceSnapshot.model_validate_json(row["payload"]) if row else None

    def latest_snapshot(self) -> ResolvedSourceSnapshot | None:
        row = self.database.execute(
            """
            SELECT payload FROM source_snapshots
            ORDER BY created_at DESC, snapshot_id DESC LIMIT 1
            """
        ).fetchone()
        return ResolvedSourceSnapshot.model_validate_json(row["payload"]) if row else None

    def activate_snapshot(
        self,
        snapshot_id: str,
        *,
        scope_id: str = "local-user",
        pinned: bool = False,
    ) -> ResolvedSourceSnapshot:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise RepositoryError("source snapshot not found")
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO active_source_snapshots(scope_id, snapshot_id, pinned, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    pinned = excluded.pinned,
                    updated_at = excluded.updated_at
                """,
                (scope_id, snapshot_id, int(pinned), _now()),
            )
        return snapshot

    def get_active_snapshot(
        self, scope_id: str = "local-user"
    ) -> tuple[ResolvedSourceSnapshot, bool] | None:
        row = self.database.execute(
            """
            SELECT s.payload, a.pinned FROM active_source_snapshots a
            JOIN source_snapshots s ON s.snapshot_id = a.snapshot_id
            WHERE a.scope_id = ?
            """,
            (scope_id,),
        ).fetchone()
        if row is None:
            return None
        return ResolvedSourceSnapshot.model_validate_json(row["payload"]), bool(row["pinned"])

    def rollback_snapshot(
        self, snapshot_id: str, *, scope_id: str = "local-user"
    ) -> ResolvedSourceSnapshot:
        return self.activate_snapshot(snapshot_id, scope_id=scope_id, pinned=True)


class SourceDiscoveryRepository:
    def __init__(self, database: Database):
        self.database = database

    def append_run(self, run: Any, decisions: tuple[Any, ...]) -> Any:
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT payload FROM source_discovery_runs WHERE discovery_run_id = ?",
                (run.discovery_run_id,),
            ).fetchone()
            if existing:
                from agentic_core.l4.discovery import SourceDiscoveryRun

                saved = SourceDiscoveryRun.model_validate_json(existing["payload"])
                if saved != run:
                    raise ImmutableConflictError("source discovery run is immutable")
                return saved
            connection.execute(
                """
                INSERT INTO source_discovery_runs(
                    discovery_run_id, user_id, started_at, status, profile_hash, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run.discovery_run_id,
                    run.user_id,
                    run.started_at.isoformat(),
                    run.status,
                    run.profile_hash,
                    _payload(run),
                ),
            )
            for decision in decisions:
                connection.execute(
                    """
                    INSERT INTO source_candidate_decisions(
                        decision_id, discovery_run_id, candidate_url, accepted, payload
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        decision.decision_id,
                        decision.discovery_run_id,
                        decision.candidate.url,
                        int(decision.accepted),
                        _payload(decision),
                    ),
                )
        return run

    def get_run(self, discovery_run_id: str) -> Any | None:
        from agentic_core.l4.discovery import SourceDiscoveryRun

        row = self.database.execute(
            "SELECT payload FROM source_discovery_runs WHERE discovery_run_id = ?",
            (discovery_run_id,),
        ).fetchone()
        return SourceDiscoveryRun.model_validate_json(row["payload"]) if row else None

    def list_runs(self, user_id: str | None = None) -> list[Any]:
        from agentic_core.l4.discovery import SourceDiscoveryRun

        if user_id is None:
            rows = self.database.execute(
                """
                SELECT payload FROM source_discovery_runs
                ORDER BY started_at, discovery_run_id
                """
            ).fetchall()
        else:
            rows = self.database.execute(
                """
                SELECT payload FROM source_discovery_runs
                WHERE user_id = ? ORDER BY started_at, discovery_run_id
                """,
                (user_id,),
            ).fetchall()
        return [SourceDiscoveryRun.model_validate_json(row["payload"]) for row in rows]

    def list_decisions(self, discovery_run_id: str) -> list[Any]:
        from agentic_core.l4.discovery import SourceCandidateDecision

        rows = self.database.execute(
            """
            SELECT payload FROM source_candidate_decisions
            WHERE discovery_run_id = ? ORDER BY decision_id
            """,
            (discovery_run_id,),
        ).fetchall()
        return [
            SourceCandidateDecision.model_validate_json(row["payload"]) for row in rows
        ]

    def append_observation(self, observation: Any) -> Any:
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT payload FROM source_observations WHERE observation_id = ?",
                (observation.observation_id,),
            ).fetchone()
            if existing:
                from agentic_core.l4.discovery import SourceObservation

                saved = SourceObservation.model_validate_json(existing["payload"])
                if saved != observation:
                    raise ImmutableConflictError("source observation is immutable")
                return saved
            if self.database.execute(
                "SELECT 1 FROM source_targets WHERE target_id = ?",
                (observation.target_id,),
            ).fetchone() is None:
                raise RepositoryError("observation target does not exist")
            connection.execute(
                """
                INSERT INTO source_observations(
                    observation_id, target_id, observed_at, payload
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.target_id,
                    observation.observed_at.isoformat(),
                    _payload(observation),
                ),
            )
        return observation

    def list_observations(self, target_id: str) -> list[Any]:
        from agentic_core.l4.discovery import SourceObservation

        rows = self.database.execute(
            """
            SELECT payload FROM source_observations
            WHERE target_id = ? ORDER BY observed_at, observation_id
            """,
            (target_id,),
        ).fetchall()
        return [SourceObservation.model_validate_json(row["payload"]) for row in rows]


class AssessmentRepository:
    def __init__(self, database: Database):
        self.database = database

    def append_assessment(self, assessment: AgentAssessment) -> AgentAssessment:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_assessments(assessment_id, item_id, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    assessment.item_id,
                    assessment.created_at.isoformat(),
                    _payload(assessment),
                ),
            )
        return assessment

    def append_ranked_signal(self, signal: RankedSignal) -> RankedSignal:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO ranked_signals(signal_id, workflow_run_id, rank, payload)
                VALUES (?, ?, ?, ?)
                """,
                (signal.signal_id, signal.workflow_run_id, signal.rank, _payload(signal)),
            )
        return signal

    def persist_final_ordering(
        self, signals: list[RankedSignal]
    ) -> list[RankedSignal]:
        """Persist one immutable, complete ordering for a workflow run.

        Hybrid ranking may already have written the same ordering.  Accept that
        idempotently, but never mix a partial or contradictory ordering with the
        final published artifact.
        """
        if not signals:
            return []
        run_ids = {signal.workflow_run_id for signal in signals}
        if len(run_ids) != 1:
            raise RepositoryError("final ordering must belong to one workflow run")
        run_id = next(iter(run_ids))
        expected_ranks = list(range(1, len(signals) + 1))
        if [signal.rank for signal in signals] != expected_ranks:
            raise RepositoryError("final ordering ranks must be contiguous")
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM ranked_signals
                WHERE workflow_run_id = ? ORDER BY rank, signal_id
                """,
                (run_id,),
            ).fetchall()
            existing = [
                RankedSignal.model_validate_json(row["payload"]) for row in rows
            ]
            if existing:
                def semantic(signal: RankedSignal) -> dict[str, Any]:
                    return signal.model_dump(mode="json", exclude={"signal_id"})

                if [semantic(item) for item in existing] != [
                    semantic(item) for item in signals
                ]:
                    raise ImmutableConflictError(
                        "workflow final ordering is already persisted differently"
                    )
                return existing
            for signal in signals:
                connection.execute(
                    """
                    INSERT INTO ranked_signals(signal_id, workflow_run_id, rank, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        signal.signal_id,
                        signal.workflow_run_id,
                        signal.rank,
                        _payload(signal),
                    ),
                )
        return signals

    def list_assessments(self, item_id: str | None = None) -> list[AgentAssessment]:
        if item_id is None:
            rows = self.database.execute(
                "SELECT payload FROM agent_assessments ORDER BY created_at, assessment_id"
            ).fetchall()
        else:
            rows = self.database.execute(
                """
                SELECT payload FROM agent_assessments
                WHERE item_id = ? ORDER BY created_at, assessment_id
                """,
                (item_id,),
            ).fetchall()
        return [AgentAssessment.model_validate_json(row["payload"]) for row in rows]

    def list_ranked_signals(self, workflow_run_id: str) -> list[RankedSignal]:
        rows = self.database.execute(
            """
            SELECT payload FROM ranked_signals
            WHERE workflow_run_id = ? ORDER BY rank, signal_id
            """,
            (workflow_run_id,),
        ).fetchall()
        return [RankedSignal.model_validate_json(row["payload"]) for row in rows]


class WorkflowRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_run(self, run: WorkflowRun) -> WorkflowRun:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs(run_id, status, started_at, finished_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.status.value,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    _payload(run),
                ),
            )
        return run

    def update_run(self, run: WorkflowRun) -> WorkflowRun:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE workflow_runs
                SET status = ?, finished_at = ?, payload = ?
                WHERE run_id = ?
                """,
                (
                    run.status.value,
                    run.finished_at.isoformat() if run.finished_at else None,
                    _payload(run),
                    run.run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RepositoryError("workflow run not found")
        return run

    def get_run(self, run_id: str) -> WorkflowRun | None:
        row = self.database.execute(
            "SELECT payload FROM workflow_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return WorkflowRun.model_validate_json(row["payload"]) if row else None

    def list_runs(self, limit: int = 100) -> list[WorkflowRun]:
        rows = self.database.execute(
            """
            SELECT payload FROM workflow_runs
            ORDER BY started_at DESC, run_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [WorkflowRun.model_validate_json(row["payload"]) for row in rows]

    def append_trace(self, trace: WorkflowStepTrace) -> WorkflowStepTrace:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO workflow_step_traces(trace_id, run_id, sequence, status, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.run_id,
                    trace.sequence,
                    trace.status.value,
                    _payload(trace),
                ),
            )
        return trace

    def list_traces(self, run_id: str) -> list[WorkflowStepTrace]:
        rows = self.database.execute(
            """
            SELECT payload FROM workflow_step_traces
            WHERE run_id = ? ORDER BY sequence
            """,
            (run_id,),
        ).fetchall()
        return [WorkflowStepTrace.model_validate_json(row["payload"]) for row in rows]


class InboxRepository:
    def __init__(self, database: Database):
        self.database = database

    def append(self, item: InboxItem) -> InboxItem:
        payload = _payload(item)
        content_hash = canonical_hash(item)
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT payload, content_hash FROM inbox_items WHERE inbox_item_id = ?",
                (item.inbox_item_id,),
            ).fetchone()
            if existing:
                if existing["content_hash"] != content_hash:
                    raise ImmutableConflictError("inbox item is immutable")
                return InboxItem.model_validate_json(existing["payload"])
            connection.execute(
                """
                INSERT INTO inbox_items(
                    inbox_item_id, user_id, created_at, url, status, content_hash, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.inbox_item_id,
                    item.user_id,
                    item.created_at.isoformat(),
                    item.url,
                    item.status.value,
                    content_hash,
                    payload,
                ),
            )
        return item

    def list_for_user(self, user_id: str) -> list[InboxItem]:
        rows = self.database.execute(
            """
            SELECT payload FROM inbox_items
            WHERE user_id = ? ORDER BY created_at, inbox_item_id
            """,
            (user_id,),
        ).fetchall()
        return [InboxItem.model_validate_json(row["payload"]) for row in rows]


class RuntimeControlRepository:
    ALLOWED_STAGES = frozenset(
        {"profile", "source_catalog", "source_discovery", "agent_ranking", "inbox"}
    )

    def __init__(self, database: Database):
        self.database = database

    def set_enabled(self, stage: str, enabled: bool) -> dict[str, Any]:
        if stage not in self.ALLOWED_STAGES:
            raise RepositoryError(f"unknown runtime stage: {stage}")
        updated_at = _now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO runtime_controls(stage, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(stage) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (stage, int(enabled), updated_at),
            )
        return {"stage": stage, "enabled": enabled, "updated_at": updated_at}

    def get_all(self) -> dict[str, bool]:
        rows = self.database.execute(
            "SELECT stage, enabled FROM runtime_controls ORDER BY stage"
        ).fetchall()
        return {row["stage"]: bool(row["enabled"]) for row in rows}
