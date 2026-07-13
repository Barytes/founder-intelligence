from pathlib import Path
import json

from agentic_core.l4.database import Database
from agentic_core.l4.migration import migrate_l4, rollback_l4_source_migration
from agentic_core.l4.source_catalog import SourceCatalog


SOURCES = """version: 1
sources:
  - id: fixture-feed
    name: Fixture Feed
    source_type: rss
    provider: fixture
    enabled: true
    connection:
      rss_url: https://example.com/feed.xml
source_templates: {}
"""


def prepare(root: Path):
    (root / "config").mkdir(parents=True)
    (root / "config/sources.yml").write_text(SOURCES, encoding="utf-8")
    (root / "config/user-profile.yml").write_text(
        "version: 1\ninterests: [MUST_NOT_IMPORT]\n", encoding="utf-8"
    )


def test_migration_dry_run_is_read_only_and_does_not_import_profile(tmp_path):
    prepare(tmp_path)
    database = Database(":memory:")
    before = (tmp_path / "config/sources.yml").read_bytes()

    report = migrate_l4(tmp_path, database=database, dry_run=True)

    assert report.status == "dry_run"
    assert report.profile_imported is False
    assert report.backup_path is None
    assert database.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM source_targets").fetchone()[0] == 0
    assert (tmp_path / "config/sources.yml").read_bytes() == before
    database.close()


def test_apply_backs_up_semantically_imports_and_can_rollback_pointer(tmp_path):
    prepare(tmp_path)
    database = Database(":memory:")
    before = (tmp_path / "config/sources.yml").read_bytes()

    report = migrate_l4(tmp_path, database=database, dry_run=False)

    assert report.status == "migrated"
    assert report.source_import.imported is True
    assert report.profile_imported is False
    assert (tmp_path / report.backup_path).read_bytes() == before
    assert (tmp_path / "config/sources.yml").read_bytes() == before
    catalog = SourceCatalog(database)
    assert len(catalog.sources.list_targets()) == 1
    active, pinned = catalog.sources.get_active_snapshot()
    assert active.snapshot_id == report.active_snapshot_id
    assert pinned is False

    rollback = rollback_l4_source_migration(
        tmp_path, report.pre_migration_snapshot_id, database=database
    )
    active, pinned = catalog.sources.get_active_snapshot()
    assert rollback["pinned"] is True
    assert active.snapshot_id == report.pre_migration_snapshot_id
    assert active.sources == ()
    assert pinned is True
    database.close()


def test_migration_is_idempotent_and_keeps_one_semantic_import(tmp_path):
    prepare(tmp_path)
    database = Database(":memory:")

    first = migrate_l4(tmp_path, database=database, dry_run=False)
    second = migrate_l4(tmp_path, database=database, dry_run=False)

    assert first.source_hash == second.source_hash
    assert second.source_import.imported is False
    assert database.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM source_targets").fetchone()[0] == 1
    assert second.original_pre_migration_snapshot_id == first.pre_migration_snapshot_id
    assert second.pre_migration_snapshot_id == first.pre_migration_snapshot_id
    assert first.migration_id != second.migration_id
    assert (tmp_path / first.history_path).exists()
    assert (tmp_path / second.history_path).exists()
    assert len(list((tmp_path / "data/migrations/history").glob("*.json"))) == 2
    database.close()


def test_reapply_repairs_legacy_report_that_overwrote_original_anchor(tmp_path):
    prepare(tmp_path)
    database = Database(":memory:")
    first = migrate_l4(tmp_path, database=database, dry_run=False)
    report_path = tmp_path / "data/migrations/l4-migration-report.json"
    legacy = first.model_dump(mode="json")
    legacy["pre_migration_snapshot_id"] = first.active_snapshot_id
    legacy.pop("original_pre_migration_snapshot_id")
    legacy.pop("migration_id")
    legacy.pop("history_path")
    report_path.write_text(json.dumps(legacy), encoding="utf-8")

    repaired = migrate_l4(tmp_path, database=database, dry_run=False)

    assert repaired.original_pre_migration_snapshot_id == first.pre_migration_snapshot_id
    assert repaired.pre_migration_snapshot_id == first.pre_migration_snapshot_id
    database.close()
