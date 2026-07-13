from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
import yaml

from agentic_core.l4.database import Database
from agentic_core.l4.domain import (
    AcquisitionBinding,
    BindingStatus,
    ConnectorType,
    ResolvedSourceSnapshot,
    SourceKind,
    SourceStatus,
    SourceTarget,
)
from agentic_core.l4.hashing import (
    canonical_hash,
    canonical_json,
    normalize_url,
    source_identity_key,
)
from agentic_core.l4.repositories import RepositoryError, SourceRepository


class CatalogContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceImportSummary(CatalogContract):
    version: Literal[1] = 1
    import_id: str
    source_hash: str
    imported: bool
    dry_run: bool
    targets_created_or_updated: int
    bindings_created_or_updated: int
    templates_imported: int
    source_ids: tuple[str, ...]


class SourceCatalogError(RuntimeError):
    pass


def _source_kind(source: dict[str, Any]) -> SourceKind:
    explicit = source.get("source_kind")
    if explicit:
        return SourceKind(explicit)
    return SourceKind.FEED


def _connector_type(source: dict[str, Any]) -> ConnectorType:
    connection = source.get("connection") or {}
    if source.get("fetcher") == "rsshub" or connection.get("rsshub_route"):
        return ConnectorType.RSSHUB
    if source.get("source_type") == "rss":
        return ConnectorType.RSS
    return ConnectorType(source.get("source_type"))


def _target_for_source(source: dict[str, Any], import_order: int) -> SourceTarget:
    connection = source.get("connection") or {}
    kind = _source_kind(source)
    external_id = source.get("canonical_external_id") or source.get("id")
    canonical_url = source.get("canonical_url") or connection.get("rss_url")
    identity = source_identity_key(
        source_kind=kind,
        provider=str(source["provider"]),
        canonical_external_id=external_id,
        canonical_url=canonical_url,
    )
    status = SourceStatus.ACTIVE if source.get("enabled") is not False else SourceStatus.PAUSED
    return SourceTarget(
        target_id=f"target-{identity[:20]}",
        source_kind=kind,
        provider=str(source["provider"]),
        canonical_external_id=external_id,
        canonical_url=canonical_url,
        display_name=str(source["name"]),
        identity_key=identity,
        status=status,
        metadata={
            "legacy_source_id": source["id"],
            "priority": source.get("priority"),
            "category": source.get("category"),
            "tags": source.get("tags") or [],
            "schedule": source.get("schedule") or {},
            "notes": source.get("notes"),
            "import_order": import_order,
        },
    )


def _binding_for_source(
    source: dict[str, Any], target_id: str, import_order: int
) -> AcquisitionBinding:
    connection = dict(source.get("connection") or {})
    credential_refs = tuple(str(value) for value in connection.pop("required_env", []) or [])
    config = {
        "legacy_source": source,
        "connection": connection,
        "import_order": import_order,
    }
    config_hash = canonical_hash(config)
    connector = _connector_type(source)
    binding_id = f"binding-{canonical_hash([target_id, connector.value, config_hash])[:20]}"
    return AcquisitionBinding(
        binding_id=binding_id,
        target_id=target_id,
        connector_type=connector,
        config=config,
        config_hash=config_hash,
        credential_refs=credential_refs,
        status=(
            BindingStatus.ACTIVE
            if source.get("enabled") is not False
            else BindingStatus.INACTIVE
        ),
    )


def snapshot_to_sources_config(snapshot: ResolvedSourceSnapshot) -> dict[str, Any]:
    sources = []
    for resolved in snapshot.sources:
        legacy = resolved.binding.config.get("legacy_source")
        if isinstance(legacy, dict):
            source = dict(legacy)
            source["enabled"] = True
            sources.append(source)
            continue

        # Discovery-created bindings are native catalog records and deliberately
        # have no legacy_source wrapper.  The current collector still consumes
        # the legacy-shaped transport contract, so adapt supported bindings at
        # this boundary instead of silently dropping them from the snapshot.
        if resolved.binding.connector_type not in {
            ConnectorType.RSS,
            ConnectorType.RSSHUB,
        }:
            continue
        target = resolved.target
        binding = resolved.binding
        connection = dict(binding.config.get("connection") or {})
        if not connection.get("rss_url"):
            continue
        metadata = target.metadata
        source = {
            "id": target.target_id,
            "name": target.display_name,
            "source_type": "rss",
            "provider": target.provider,
            "fetcher": (
                "rsshub"
                if binding.connector_type == ConnectorType.RSSHUB
                else "rss"
            ),
            "enabled": True,
            "priority": metadata.get("priority") or "medium",
            "category": metadata.get("category") or target.source_kind.value,
            "tags": list(metadata.get("tags") or []),
            "schedule": metadata.get("schedule") or {},
            "connection": connection,
            "source_target_id": target.target_id,
            "acquisition_binding_id": binding.binding_id,
            "tracking_state": target.status.value,
        }
        for key in ("timeout_seconds", "max_items"):
            if key in binding.config:
                source[key] = binding.config[key]
        if "max_items" not in source and "item_quota" in binding.config:
            source["max_items"] = binding.config["item_quota"]
        sources.append(source)
    return {"version": 1, "sources": sources, "source_templates": {}}


class SourceCatalog:
    def __init__(self, database: Database):
        self.database = database
        self.sources = SourceRepository(database)

    def import_yaml_path(self, path: str | Path, *, dry_run: bool = False) -> SourceImportSummary:
        return self.import_yaml_text(
            Path(path).read_text(encoding="utf-8"),
            dry_run=dry_run,
        )

    def import_yaml_text(self, content: str, *, dry_run: bool = False) -> SourceImportSummary:
        try:
            config = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise SourceCatalogError(f"invalid sources YAML: {exc}") from exc
        if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
            raise SourceCatalogError("sources YAML must contain a sources array")
        source_hash = canonical_hash(config)
        existing = self.database.execute(
            "SELECT payload FROM source_imports WHERE source_hash = ?",
            (source_hash,),
        ).fetchone()
        if existing:
            previous = SourceImportSummary.model_validate_json(existing["payload"])
            return previous.model_copy(update={"imported": False, "dry_run": dry_run})

        prepared: list[tuple[SourceTarget, AcquisitionBinding]] = []
        feed_target_by_url: dict[str, SourceTarget] = {}
        seen_source_ids: set[str] = set()
        for index, source in enumerate(config["sources"]):
            if not isinstance(source, dict):
                raise SourceCatalogError(f"source at index {index} must be a mapping")
            for key in ("id", "name", "source_type", "provider", "enabled"):
                if key not in source:
                    raise SourceCatalogError(f"source at index {index} missing {key}")
            source_id = str(source["id"])
            if source_id in seen_source_ids:
                raise SourceCatalogError(f"duplicate source id: {source_id}")
            seen_source_ids.add(source_id)
            try:
                target = _target_for_source(source, index)
                rss_url = (source.get("connection") or {}).get("rss_url")
                if rss_url:
                    normalized_url = normalize_url(str(rss_url))
                    target = feed_target_by_url.setdefault(normalized_url, target)
                prepared.append(
                    (target, _binding_for_source(source, target.target_id, index))
                )
            except (ValueError, KeyError) as exc:
                raise SourceCatalogError(f"invalid source {source_id}: {exc}") from exc

        templates = config.get("source_templates") or {}
        if not isinstance(templates, dict):
            raise SourceCatalogError("source_templates must be a mapping")
        for template_id, template in templates.items():
            if not isinstance(template, dict) or not template.get("provider") or not template.get("source_type"):
                raise SourceCatalogError(f"invalid source template: {template_id}")

        import_id = f"source-import-{uuid4()}"
        summary = SourceImportSummary(
            import_id=import_id,
            source_hash=source_hash,
            imported=not dry_run,
            dry_run=dry_run,
            targets_created_or_updated=len({target.identity_key for target, _ in prepared}),
            bindings_created_or_updated=len(prepared),
            templates_imported=len(templates),
            source_ids=tuple(sorted(seen_source_ids)),
        )
        if dry_run:
            return summary

        with self.database.transaction() as connection:
            for target, binding in prepared:
                saved_target = self.sources.replace_target_from_import(
                    target,
                    reason=f"yaml_import:{import_id}",
                )
                if binding.target_id != saved_target.target_id:
                    binding = binding.model_copy(update={"target_id": saved_target.target_id})
                for existing_binding in self.sources.list_bindings(saved_target.target_id):
                    if (
                        existing_binding.connector_type == binding.connector_type
                        and existing_binding.config_hash != binding.config_hash
                        and existing_binding.status == BindingStatus.ACTIVE
                    ):
                        self.sources.set_binding_status(
                            existing_binding.binding_id,
                            BindingStatus.INACTIVE,
                            reason=f"superseded_by_import:{import_id}",
                        )
                self.sources.add_binding(
                    binding,
                    reason=f"yaml_import:{import_id}",
                )
            for template_id, template in templates.items():
                connection.execute(
                    """
                    INSERT INTO source_templates(
                        template_record_id, template_id, source_hash,
                        provider, source_type, imported_at, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{template_id}:{source_hash[:16]}",
                        str(template_id),
                        source_hash,
                        str(template["provider"]),
                        str(template["source_type"]),
                        datetime.now(timezone.utc).isoformat(),
                        canonical_json(template),
                    ),
                )
            connection.execute(
                """
                INSERT INTO source_imports(import_id, source_hash, imported_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    import_id,
                    source_hash,
                    datetime.now(timezone.utc).isoformat(),
                    summary.model_dump_json(),
                ),
            )
        return summary

    def create_snapshot(
        self, *, snapshot_id: str, workflow_run_id: str | None = None
    ) -> ResolvedSourceSnapshot:
        return self.sources.create_snapshot(
            snapshot_id=snapshot_id,
            workflow_run_id=workflow_run_id,
        )

    def source_rows(self) -> list[dict[str, Any]]:
        rows = []
        for target in self.sources.list_targets():
            bindings = self.sources.list_bindings(target.target_id)
            legacy = next(
                (
                    binding.config.get("legacy_source")
                    for binding in bindings
                    if isinstance(binding.config.get("legacy_source"), dict)
                ),
                {},
            )
            rows.append(
                {
                    "id": legacy.get("id") or target.target_id,
                    "name": target.display_name,
                    "source_type": legacy.get("source_type") or target.source_kind.value,
                    "provider": target.provider,
                    "fetcher": legacy.get("fetcher"),
                    "enabled": target.status == SourceStatus.ACTIVE,
                    "priority": target.metadata.get("priority"),
                    "category": target.metadata.get("category"),
                    "tags": target.metadata.get("tags") or [],
                    "tracking_state": target.status.value,
                    "target_id": target.target_id,
                    "type": legacy.get("source_type") or target.source_kind.value,
                    "runnable": any(
                        binding.status == BindingStatus.ACTIVE for binding in bindings
                    ),
                    "toggleable": bool(bindings),
                    "cadence": (
                        f"每 {target.metadata.get('schedule', {}).get('refresh_interval_minutes')} 分钟"
                        if target.metadata.get("schedule", {}).get("refresh_interval_minutes")
                        else "按刷新运行"
                    ),
                    "signal": target.canonical_url or "Configured target",
                }
            )
        return rows

    def set_legacy_source_enabled(self, source_id: str, enabled: bool) -> dict[str, Any]:
        for target in self.sources.list_targets():
            bindings = self.sources.list_bindings(target.target_id)
            if target.target_id == source_id or any(
                binding.config.get("legacy_source", {}).get("id") == source_id
                for binding in bindings
            ):
                target_status = SourceStatus.ACTIVE if enabled else SourceStatus.PAUSED
                binding_status = BindingStatus.ACTIVE if enabled else BindingStatus.INACTIVE
                updated = self.sources.set_target_status(
                    target.target_id,
                    target_status,
                    reason="dashboard_toggle",
                )
                for binding in bindings:
                    self.sources.set_binding_status(
                        binding.binding_id,
                        binding_status,
                        reason="dashboard_toggle",
                    )
                return next(
                    row for row in self.source_rows() if row["target_id"] == updated.target_id
                )
        raise RepositoryError("source not found")
