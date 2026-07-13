from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentic_core.l4.database import Database
from agentic_core.l4.hashing import canonical_hash
from agentic_core.l4.source_catalog import SourceCatalog, SourceImportSummary


class MigrationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class L4MigrationReport(MigrationContract):
    version: Literal[1] = 1
    status: str
    dry_run: bool
    source_hash: str
    backup_path: str | None
    source_import: SourceImportSummary
    pre_migration_snapshot_id: str | None
    active_snapshot_id: str | None
    profile_imported: bool = False
    legacy_profile_path: str = "config/user-profile.yml"
    profile_example_path: str = "config/user-profile.example.yml"
    compatibility_fallback_env: str = "FI_L4_LEGACY_FALLBACK"
    migrated_at: datetime
    migration_id: str = Field(default_factory=lambda: f"migration-{uuid4()}")
    original_pre_migration_snapshot_id: str | None = None
    history_path: str | None = None


def migrate_l4(
    root: str | Path,
    *,
    database: Database | None = None,
    dry_run: bool = True,
) -> L4MigrationReport:
    root_path = Path(root).resolve()
    sources_path = root_path / "config/sources.yml"
    source_bytes = sources_path.read_bytes()
    source_hash = canonical_hash(source_bytes.decode("utf-8"))
    owned = database is None
    database = database or Database(
        ":memory:" if dry_run else root_path / "data/app/founder-intelligence.db"
    )
    catalog = SourceCatalog(database)
    report_path = root_path / "data/migrations/l4-migration-report.json"
    previous_report: L4MigrationReport | None = None
    if not dry_run and report_path.exists():
        try:
            previous_report = L4MigrationReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
        except (ValueError, OSError):
            previous_report = None
    conventional_anchor = f"source-snapshot-pre-migration-{source_hash[:16]}"
    existing_conventional_anchor = catalog.sources.get_snapshot(
        conventional_anchor
    )
    original_anchor = (
        previous_report.original_pre_migration_snapshot_id
        if previous_report is not None
        and previous_report.original_pre_migration_snapshot_id
        else conventional_anchor
        if existing_conventional_anchor is not None
        else previous_report.pre_migration_snapshot_id
        if previous_report is not None
        else None
    )
    pre_snapshot = None
    if not dry_run:
        pre_snapshot = (
            catalog.sources.get_snapshot(original_anchor)
            if original_anchor
            else None
        )
        if pre_snapshot is None:
            pre_snapshot = catalog.create_snapshot(
                snapshot_id=conventional_anchor
            )
            original_anchor = pre_snapshot.snapshot_id
    summary = catalog.import_yaml_path(sources_path, dry_run=dry_run)
    backup_path: Path | None = None
    active_snapshot_id: str | None = pre_snapshot.snapshot_id if pre_snapshot else None
    if not dry_run:
        backup_path = (
            root_path
            / "data/migrations"
            / f"sources-{source_hash[:16]}.yml"
        )
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if not backup_path.exists():
            shutil.copy2(sources_path, backup_path)
        post = catalog.create_snapshot(
            snapshot_id=f"source-snapshot-migrated-{source_hash[:16]}"
        )
        catalog.sources.activate_snapshot(post.snapshot_id, pinned=False)
        active_snapshot_id = post.snapshot_id
    migration_id = f"migration-{uuid4()}"
    history_path = (
        root_path / "data/migrations/history" / f"{migration_id}.json"
        if not dry_run
        else None
    )
    report = L4MigrationReport(
        status="dry_run" if dry_run else "migrated",
        dry_run=dry_run,
        source_hash=source_hash,
        backup_path=str(backup_path.relative_to(root_path)) if backup_path else None,
        source_import=summary,
        pre_migration_snapshot_id=pre_snapshot.snapshot_id if pre_snapshot else None,
        active_snapshot_id=active_snapshot_id,
        profile_imported=False,
        migrated_at=datetime.now(timezone.utc),
        migration_id=migration_id,
        original_pre_migration_snapshot_id=original_anchor,
        history_path=(
            str(history_path.relative_to(root_path)) if history_path else None
        ),
    )
    if not dry_run:
        serialized = (
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n"
        )
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(serialized, encoding="utf-8")
        report_path.write_text(serialized, encoding="utf-8")
    if owned:
        database.close()
    return report


def rollback_l4_source_migration(
    root: str | Path,
    snapshot_id: str,
    *,
    database: Database | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    owned = database is None
    database = database or Database(
        root_path / "data/app/founder-intelligence.db"
    )
    snapshot = SourceCatalog(database).sources.rollback_snapshot(snapshot_id)
    result = {
        "status": "rolled_back",
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "pinned": True,
    }
    if owned:
        database.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Founder Intelligence to L4 stores")
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback-source-snapshot")
    args = parser.parse_args(argv)
    if args.rollback_source_snapshot:
        result = rollback_l4_source_migration(
            args.root, args.rollback_source_snapshot
        )
    else:
        result = migrate_l4(args.root, dry_run=not args.apply).model_dump(mode="json")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
