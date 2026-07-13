from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any


class DatabaseError(RuntimeError):
    pass


class DatabaseCorruptionError(DatabaseError):
    pass


class MigrationError(DatabaseError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    apply: Callable[[sqlite3.Connection], None]


def _create_schema_v1(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE context_events (
            event_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            content_hash TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_context_events_user_time ON context_events(user_id, occurred_at, event_id)",
        """
        CREATE TABLE profile_snapshots (
            profile_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            profile_hash TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_profile_snapshots_user_time ON profile_snapshots(user_id, created_at, profile_id)",
        """
        CREATE TABLE active_profiles (
            user_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES profile_snapshots(profile_id),
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE source_targets (
            target_id TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL UNIQUE,
            source_kind TEXT NOT NULL,
            provider TEXT NOT NULL,
            canonical_external_id TEXT,
            canonical_url TEXT,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE source_target_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT NOT NULL REFERENCES source_targets(target_id),
            status TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE acquisition_bindings (
            binding_id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES source_targets(target_id),
            connector_type TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(target_id, connector_type, config_hash)
        )
        """,
        """
        CREATE TABLE binding_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            binding_id TEXT NOT NULL REFERENCES acquisition_bindings(binding_id),
            status TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE source_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            snapshot_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            workflow_run_id TEXT,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE agent_assessments (
            assessment_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_agent_assessments_item ON agent_assessments(item_id, created_at)",
        """
        CREATE TABLE ranked_signals (
            signal_id TEXT PRIMARY KEY,
            workflow_run_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_ranked_signals_run_rank ON ranked_signals(workflow_run_id, rank)",
        """
        CREATE TABLE workflow_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE workflow_step_traces (
            trace_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
            sequence INTEGER NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(run_id, sequence)
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)

    append_only = (
        "context_events",
        "profile_snapshots",
        "source_target_history",
        "binding_history",
        "source_snapshots",
        "agent_assessments",
        "ranked_signals",
        "workflow_step_traces",
    )
    for table in append_only:
        connection.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
        )
        connection.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
        )


def _create_source_import_schema_v2(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE source_imports (
            import_id TEXT PRIMARY KEY,
            source_hash TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE source_templates (
            template_record_id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            provider TEXT NOT NULL,
            source_type TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(template_id, source_hash)
        )
        """
    )
    for table in ("source_imports", "source_templates"):
        connection.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
        )
        connection.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
        )


def _create_inbox_schema_v3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE inbox_items (
            inbox_item_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX idx_inbox_items_user_time ON inbox_items(user_id, created_at, inbox_item_id)"
    )
    connection.execute(
        "CREATE TRIGGER inbox_items_no_update BEFORE UPDATE ON inbox_items "
        "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
    )
    connection.execute(
        "CREATE TRIGGER inbox_items_no_delete BEFORE DELETE ON inbox_items "
        "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
    )


def _create_source_discovery_schema_v4(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE source_discovery_runs (
            discovery_run_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            status TEXT NOT NULL,
            profile_hash TEXT,
            payload TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_source_discovery_user_time ON source_discovery_runs(user_id, started_at, discovery_run_id)",
        """
        CREATE TABLE source_candidate_decisions (
            decision_id TEXT PRIMARY KEY,
            discovery_run_id TEXT NOT NULL REFERENCES source_discovery_runs(discovery_run_id),
            candidate_url TEXT NOT NULL,
            accepted INTEGER NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE source_observations (
            observation_id TEXT PRIMARY KEY,
            target_id TEXT NOT NULL REFERENCES source_targets(target_id),
            observed_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_source_observations_target_time ON source_observations(target_id, observed_at, observation_id)",
    )
    for statement in statements:
        connection.execute(statement)
    for table in (
        "source_discovery_runs",
        "source_candidate_decisions",
        "source_observations",
    ):
        connection.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
        )
        connection.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
        )


def _create_control_plane_schema_v5(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE active_source_snapshots (
            scope_id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
            pinned INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE runtime_controls (
            stage TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


DEFAULT_MIGRATIONS = (
    Migration(1, _create_schema_v1),
    Migration(2, _create_source_import_schema_v2),
    Migration(3, _create_inbox_schema_v3),
    Migration(4, _create_source_discovery_schema_v4),
    Migration(5, _create_control_plane_schema_v5),
)


class Database:
    def __init__(
        self,
        path: str | Path = "data/app/founder-intelligence.db",
        *,
        migrations: Sequence[Migration] = DEFAULT_MIGRATIONS,
        auto_migrate: bool = True,
    ):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._savepoint_counter = 0
        try:
            self.connection = sqlite3.connect(
                self.path,
                isolation_level=None,
                check_same_thread=False,
                timeout=30,
            )
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self.connection.execute("PRAGMA journal_mode = WAL")
            result = self.connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise DatabaseCorruptionError(f"database integrity check failed: {result}")
        except sqlite3.DatabaseError as exc:
            raise DatabaseCorruptionError(
                f"database is unreadable and was not replaced: {self.path}"
            ) from exc

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        if auto_migrate:
            self.apply_migrations(migrations)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self.connection.in_transaction:
                self._savepoint_counter += 1
                name = f"sp_{self._savepoint_counter}"
                self.connection.execute(f"SAVEPOINT {name}")
                try:
                    yield self.connection
                except BaseException:
                    self.connection.execute(f"ROLLBACK TO {name}")
                    self.connection.execute(f"RELEASE {name}")
                    raise
                else:
                    self.connection.execute(f"RELEASE {name}")
                return

            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except BaseException:
                self.connection.rollback()
                raise
            else:
                self.connection.commit()

    def apply_migrations(self, migrations: Sequence[Migration]) -> None:
        versions = [migration.version for migration in migrations]
        if versions != sorted(set(versions)):
            raise MigrationError("migration versions must be unique and ordered")
        applied = {
            row["version"]
            for row in self.connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        for migration in migrations:
            if migration.version in applied:
                continue
            try:
                with self.transaction() as connection:
                    if connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?",
                        (migration.version,),
                    ).fetchone():
                        continue
                    migration.apply(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (
                            migration.version,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
            except sqlite3.DatabaseError as exc:
                raise MigrationError(
                    f"migration {migration.version} failed and was rolled back"
                ) from exc

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
