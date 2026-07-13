from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from agentic_core.feature_flags import L4FeatureFlags
from agentic_core.l4.database import Database
from agentic_core.l4.domain import (
    AcquisitionBinding,
    BindingStatus,
    ConnectorType,
    SourceKind,
    SourceStatus,
    SourceTarget,
)
from agentic_core.l4.hashing import canonical_hash, source_identity_key
from agentic_core.l4.source_catalog import (
    SourceCatalog,
    SourceCatalogError,
    snapshot_to_sources_config,
)
from agentic_core.pipeline import fetch_rss
from agentic_core.pipeline.runner import PipelineRunner
from web_workbench.app import create_app


ROOT = Path(__file__).resolve().parents[1]


def current_sources_text() -> str:
    return (ROOT / "config/sources.yml").read_text(encoding="utf-8")


def test_current_yaml_import_preserves_semantics_and_templates_without_activating_them():
    database = Database(":memory:")
    catalog = SourceCatalog(database)

    summary = catalog.import_yaml_text(current_sources_text())

    assert summary.imported is True
    assert summary.targets_created_or_updated == 4
    assert summary.bindings_created_or_updated == 4
    assert summary.templates_imported == 2
    assert len(catalog.sources.list_targets()) == 4
    assert len(catalog.sources.list_bindings()) == 4
    assert database.execute("SELECT COUNT(*) FROM source_templates").fetchone()[0] == 2
    assert all(
        target.source_kind.value != "template"
        for target in catalog.sources.list_targets()
    )
    assert sum(target.status == SourceStatus.ACTIVE for target in catalog.sources.list_targets()) == 3


def test_import_is_idempotent_across_yaml_formatting_changes():
    database = Database(":memory:")
    catalog = SourceCatalog(database)
    first = catalog.import_yaml_text(current_sources_text())
    reformatted = yaml.safe_dump(
        yaml.safe_load(current_sources_text()),
        sort_keys=True,
        allow_unicode=True,
    )

    repeated = catalog.import_yaml_text(reformatted)

    assert first.source_hash == repeated.source_hash
    assert repeated.imported is False
    assert len(catalog.sources.list_targets()) == 4
    assert len(catalog.sources.list_bindings()) == 4
    assert database.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 1


def test_duplicate_feed_urls_converge_to_one_target_with_multiple_bindings():
    config = {
        "version": 1,
        "sources": [
            {
                "id": source_id,
                "name": source_id,
                "source_type": "rss",
                "provider": "web",
                "fetcher": "rss",
                "enabled": True,
                "connection": {"rss_url": "https://example.com/feed"},
            }
            for source_id in ("one", "two")
        ],
        "source_templates": {},
    }
    catalog = SourceCatalog(Database(":memory:"))

    catalog.import_yaml_text(yaml.safe_dump(config))

    assert len(catalog.sources.list_targets()) == 1
    assert len(catalog.sources.list_bindings()) == 2


def test_invalid_source_rolls_back_entire_import():
    config = yaml.safe_load(current_sources_text())
    config["sources"].append({"id": "broken"})
    database = Database(":memory:")
    catalog = SourceCatalog(database)

    with pytest.raises(SourceCatalogError, match="missing name"):
        catalog.import_yaml_text(yaml.safe_dump(config))

    assert catalog.sources.list_targets() == []
    assert database.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 0


def test_dry_run_has_no_side_effects():
    database = Database(":memory:")
    catalog = SourceCatalog(database)

    summary = catalog.import_yaml_text(current_sources_text(), dry_run=True)

    assert summary.dry_run is True
    assert summary.imported is False
    assert catalog.sources.list_targets() == []
    assert database.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 0


def test_explicit_reimport_updates_catalog_and_deactivates_superseded_binding():
    database = Database(":memory:")
    catalog = SourceCatalog(database)
    catalog.import_yaml_text(current_sources_text())
    changed = yaml.safe_load(current_sources_text())
    source = changed["sources"][0]
    source["name"] = "Renamed GitHub Feed"
    source["connection"]["rss_url"] = "http://localhost:1200/github/trending/daily/python"
    source["connection"]["rsshub_route"] = "/github/trending/daily/python"

    summary = catalog.import_yaml_text(yaml.safe_dump(changed, allow_unicode=True))
    rows = catalog.source_rows()
    github = next(row for row in rows if row["id"] == "github-trending-daily")
    target = catalog.sources.get_target(github["target_id"])
    bindings = catalog.sources.list_bindings(target.target_id)

    assert summary.imported is True
    assert target.display_name == "Renamed GitHub Feed"
    assert sum(binding.status == BindingStatus.ACTIVE for binding in bindings) == 1
    assert sum(binding.status == BindingStatus.INACTIVE for binding in bindings) == 1


def test_snapshot_is_immutable_hashed_and_reconstructs_active_legacy_sources():
    database = Database(":memory:")
    catalog = SourceCatalog(database)
    catalog.import_yaml_text(current_sources_text())

    snapshot = catalog.create_snapshot(snapshot_id="snapshot-1", workflow_run_id="run-1")
    config = snapshot_to_sources_config(snapshot)

    assert snapshot.workflow_run_id == "run-1"
    assert len(snapshot.snapshot_hash) == 64
    assert {source["id"] for source in config["sources"]} == {
        "github-trending-daily",
        "zhihu-hot",
        "bilibili-popular-all",
    }
    assert all(source["enabled"] for source in config["sources"])


@pytest.mark.parametrize(
    ("connector_type", "expected_fetcher"),
    [(ConnectorType.RSS, "rss"), (ConnectorType.RSSHUB, "rsshub")],
)
def test_snapshot_adapts_native_discovered_feed_binding_for_collection(
    connector_type, expected_fetcher, monkeypatch
):
    catalog = SourceCatalog(Database(":memory:"))
    url = "https://example.com/discovered.xml"
    identity = source_identity_key(
        source_kind=SourceKind.FEED,
        provider="discovery",
        canonical_external_id=None,
        canonical_url=url,
    )
    target = SourceTarget(
        target_id="target-discovered",
        source_kind=SourceKind.FEED,
        provider="discovery",
        canonical_url=url,
        display_name="Discovered feed",
        identity_key=identity,
        status=SourceStatus.PROBATION,
        metadata={"priority": "high", "tags": ["agent"]},
    )
    catalog.sources.upsert_target(target, reason="test_discovery")
    binding_config = {
        "connection": {"rss_url": url},
        "item_quota": 7,
    }
    catalog.sources.add_binding(
        AcquisitionBinding(
            binding_id="binding-discovered",
            target_id=target.target_id,
            connector_type=connector_type,
            config=binding_config,
            config_hash=canonical_hash(binding_config),
        )
    )

    config = snapshot_to_sources_config(
        catalog.create_snapshot(snapshot_id="snapshot-discovered")
    )

    assert config["sources"] == [
        {
            "id": "target-discovered",
            "name": "Discovered feed",
            "source_type": "rss",
            "provider": "discovery",
            "fetcher": expected_fetcher,
            "enabled": True,
            "priority": "high",
            "category": "feed",
            "tags": ["agent"],
            "schedule": {},
            "connection": {"rss_url": url},
            "source_target_id": "target-discovered",
            "acquisition_binding_id": "binding-discovered",
            "tracking_state": "probation",
            "max_items": 7,
        }
    ]
    xml = "<rss><channel>" + "".join(
        f"<item><guid>{index}</guid><title>Item {index}</title></item>"
        for index in range(10)
    ) + "</channel></rss>"
    monkeypatch.setattr(
        fetch_rss,
        "fetch_xml",
        lambda *_args: (xml, SimpleNamespace(headers={})),
    )
    collected = fetch_rss.fetch(config, {"fetch": {}})["results"][0]
    assert collected["source_id"] == "target-discovered"
    assert len(collected["items"]) == 7


def test_rss_fetch_selection_is_semantically_equal_under_catalog(monkeypatch):
    source_config = yaml.safe_load(current_sources_text())
    catalog = SourceCatalog(Database(":memory:"))
    catalog.import_yaml_text(current_sources_text())
    snapshot_config = snapshot_to_sources_config(
        catalog.create_snapshot(snapshot_id="snapshot-1")
    )

    monkeypatch.setattr(
        fetch_rss,
        "fetch_source",
        lambda source, _rules, _context: {
            "source_id": source["id"],
            "status": "ok",
            "items": [],
            "errors": [],
        },
    )
    original = fetch_rss.fetch(source_config, {"fetch": {}})
    catalog_result = fetch_rss.fetch(snapshot_config, {"fetch": {}})

    assert [result["source_id"] for result in original["results"]] == [
        result["source_id"] for result in catalog_result["results"]
    ]


def test_catalog_toggle_never_writes_yaml(tmp_path):
    path = tmp_path / "sources.yml"
    path.write_text(current_sources_text(), encoding="utf-8")
    before = sha256(path.read_bytes()).hexdigest()
    catalog = SourceCatalog(Database(":memory:"))
    catalog.import_yaml_path(path)

    row = catalog.set_legacy_source_enabled("github-trending-daily", False)

    assert row["enabled"] is False
    assert sha256(path.read_bytes()).hexdigest() == before


def test_runner_uses_one_catalog_snapshot_for_fetch_and_ingestion(monkeypatch, tmp_path):
    for name in (
        "sources.yml",
        "ingestion-rules.yml",
        "user-profile.yml",
        "signal-rules.yml",
    ):
        target = tmp_path / "config" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / "config" / name).read_bytes())
    sources_path = tmp_path / "config/sources.yml"
    before = sha256(sources_path.read_bytes()).hexdigest()
    catalog = SourceCatalog(Database(":memory:"))
    catalog.import_yaml_path(sources_path)

    def fake_fetch(config, _rules):
        return {
            "run_id": "catalog-run-1",
            "adapter": "rss",
            "contract_version": 1,
            "fetched_at": "2026-07-12T00:00:00+00:00",
            "results": [
                {
                    "source_id": source["id"],
                    "source_type": source["source_type"],
                    "provider": source["provider"],
                    "fetched_at": "2026-07-12T00:00:00+00:00",
                    "status": "ok",
                    "items": [],
                    "errors": [],
                }
                for source in config["sources"]
            ],
        }

    monkeypatch.setattr(fetch_rss, "fetch", fake_fetch)
    runner = PipelineRunner(
        root=tmp_path,
        l4_feature_flags=L4FeatureFlags(source_catalog_enabled=True),
        source_catalog=catalog,
    )

    status = runner.refresh()

    assert status["status"] == "succeeded_empty"
    assert status["source_snapshot_id"].startswith("source-snapshot-refresh-")
    assert [
        row["source_id"] for row in status["adapter_summary"]["source_results"]
    ] == ["github-trending-daily", "zhihu-hot", "bilibili-popular-all"]
    assert sha256(sources_path.read_bytes()).hexdigest() == before


def test_web_source_api_reads_and_toggles_catalog_without_yaml_write(tmp_path):
    sources_path = tmp_path / "config/sources.yml"
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(current_sources_text(), encoding="utf-8")
    before = sha256(sources_path.read_bytes()).hexdigest()
    database = Database(":memory:")
    SourceCatalog(database).import_yaml_path(sources_path)
    app = create_app(
        repo_root=tmp_path,
        auto_start_rsshub=False,
        l4_database=database,
        l4_feature_flags=L4FeatureFlags(source_catalog_enabled=True),
    )
    client = TestClient(app)

    listed = client.get("/api/sources")
    toggled = client.post(
        "/api/sources/github-trending-daily",
        headers={"origin": "http://testserver"},
        json={"enabled": False},
    )

    assert listed.json()["source_of_truth"] == "sqlite_catalog"
    assert len(listed.json()["sources"]) == 4
    assert toggled.json()["source"]["enabled"] is False
    assert toggled.json()["source_of_truth"] == "sqlite_catalog"
    assert sha256(sources_path.read_bytes()).hexdigest() == before
    database.close()
