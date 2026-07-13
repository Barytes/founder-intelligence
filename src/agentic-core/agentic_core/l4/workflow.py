from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml

from agentic_core.config import load_agentic_config
from agentic_core.l4.agents.news_assessment import PydanticAINewsAssessmentAgent
from agentic_core.l4.agents.profile_compiler import (
    ProfileCompiler,
    ProfileService,
    active_events,
)
from agentic_core.l4.agents.source_discovery import PydanticAISourceDiscoveryAgent
from agentic_core.l4.connectors.base import (
    ConnectorErrorCode,
    ConnectorLimits,
    UrllibHTTPClient,
)
from agentic_core.l4.connectors.feed_discovery import (
    discover_alternate_feed,
    validate_discovery_url,
)
from agentic_core.l4.connectors.rss import RSSConnector
from agentic_core.l4.database import Database
from agentic_core.l4.discovery import (
    CandidateProbeResult,
    DiscoveryCadenceState,
    SourceDiscoveryService,
    decide_source_discovery_due,
)
from agentic_core.l4.domain import (
    AcquisitionBinding,
    AgentNodeAudit,
    BindingStatus,
    ConnectorType,
    EffectiveProfile,
    RankedSignal,
    ScoreProvenance,
    SourceKind,
    StepStatus,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepTrace,
)
from agentic_core.l4.hashing import canonical_hash
from agentic_core.l4.ranking import HybridRankingService
from agentic_core.l4.repositories import (
    AssessmentRepository,
    ContextEventRepository,
    InboxRepository,
    ProfileRepository,
    SourceDiscoveryRepository,
    SourceRepository,
    RuntimeControlRepository,
    WorkflowRepository,
)
from agentic_core.l4.search import BraveSearchProvider
from agentic_core.l4.source_catalog import SourceCatalog, snapshot_to_sources_config
from agentic_core.pipeline import build_signals, store_canonical_jsonl
from agentic_core.runtime.pydantic_ai_runtime import PydanticAIRuntime
from agentic_core.tools.registry import ToolRegistry


L4_STEP_ORDER = (
    "persist_events",
    "compile_resolve_profile",
    "decide_discover_sources",
    "resolve_source_snapshot",
    "collect",
    "ingest_store",
    "baseline_score",
    "agent_assess",
    "validate_compose",
    "publish",
    "trace",
)


class _UnavailableAssessmentAgent:
    model_id = "unavailable"
    prompt_version = "news-assessment-agent-v2"

    def assess(self, **_kwargs):
        raise RuntimeError("assessment runtime unavailable")


class _UnavailableDiscoveryAgent:
    model_id = "unavailable"
    prompt_version = "source-discovery-agent-v1"

    def discover(self, *_args, **_kwargs):
        raise RuntimeError("source discovery runtime unavailable")


class L4WorkflowRunner:
    """Fixed L4 orchestration over the existing PipelineRunner lifecycle primitives."""

    def __init__(self, base_runner: Any):
        self.base = base_runner
        self.root = Path(base_runner.root)
        self.flags = base_runner.l4_feature_flags
        self.database = base_runner.l4_database
        self.owns_database = self.database is None
        if self.database is None:
            self.database = Database(self.root / "data/app/founder-intelligence.db")
        self.events = ContextEventRepository(self.database)
        self.profiles = base_runner.profile_repository or ProfileRepository(self.database)
        self.sources = (
            base_runner.source_catalog.sources
            if base_runner.source_catalog is not None
            else SourceRepository(self.database)
        )
        self.source_catalog = base_runner.source_catalog or SourceCatalog(self.database)
        self.inbox = base_runner.inbox_repository or InboxRepository(self.database)
        self.discovery_repository = SourceDiscoveryRepository(self.database)
        self.assessments = AssessmentRepository(self.database)
        self.workflows = base_runner.workflow_repository or WorkflowRepository(self.database)
        controls = RuntimeControlRepository(self.database).get_all()
        flag_updates = {
            f"{stage}_enabled": False
            for stage, enabled in controls.items()
            if not enabled and hasattr(self.flags, f"{stage}_enabled")
        }
        if flag_updates:
            self.flags = self.flags.model_copy(update=flag_updates)
        self.runtime: PydanticAIRuntime | None = None
        self.profile_service = base_runner.profile_service
        self.discovery_service = base_runner.source_discovery_service
        self.ranking_service = base_runner.ranking_service
        if (
            self.ranking_service is not None
            and getattr(self.ranking_service, "repository", None) is None
        ):
            self.ranking_service.repository = self.assessments
        self.profile = EffectiveProfile(user_id=base_runner.user_id, initialized=False)
        self.discovery_result = None
        self.baseline_output: dict[str, Any] | None = None
        self.final_output: dict[str, Any] | None = None
        self.degraded_reasons: list[str] = []
        self.usage: dict[str, Any] = {}
        self._prepare_default_services()

    def _prepare_default_services(self) -> None:
        if not (
            self.flags.profile_enabled
            or self.flags.source_discovery_enabled
            or self.flags.agent_ranking_enabled
        ):
            return
        config_path = self.root / "config/agentic-core.example.yml"
        local_path = self.root / "config/agentic-core.local.yml"
        try:
            config = load_agentic_config(config_path, local_config_path=local_path)
            self.runtime = PydanticAIRuntime(config=config, tools=ToolRegistry())
            model_id = config.provider.model
        except Exception:
            config = None
            model_id = "unavailable"
        if self.ranking_service is None and self.flags.agent_ranking_enabled:
            agent = (
                PydanticAINewsAssessmentAgent(runtime=self.runtime, model_id=model_id)
                if self.runtime is not None
                else _UnavailableAssessmentAgent()
            )
            self.ranking_service = HybridRankingService(
                agent=agent,
                repository=self.assessments,
            )
        if self.discovery_service is None and self.flags.source_discovery_enabled:
            discovery_agent = (
                PydanticAISourceDiscoveryAgent(runtime=self.runtime, model_id=model_id)
                if self.runtime is not None
                else _UnavailableDiscoveryAgent()
            )
            self.discovery_service = SourceDiscoveryService(
                provider=BraveSearchProvider(),
                agent=discovery_agent,
                sources=self.sources,
                discovery=self.discovery_repository,
                probe=self._probe_candidate,
                url_validator=validate_discovery_url,
            )
        if self.profile_service is None and self.flags.profile_enabled:
            self.profile_service = ProfileService(
                events=self.events,
                profiles=self.profiles,
                compiler=ProfileCompiler(
                    repository=self.profiles,
                    runtime=self.runtime,
                    model_id=model_id,
                ),
            )

    def _probe_candidate(self, candidate: Any, target_id: str) -> CandidateProbeResult:
        feed_url = candidate.url
        if candidate.source_kind in {SourceKind.WEBSITE, SourceKind.PUBLICATION}:
            try:
                feed_url = discover_alternate_feed(candidate.url) or ""
            except Exception as exc:
                return CandidateProbeResult(
                    valid=False,
                    reject_reason=f"feed_discovery_failed:{exc.__class__.__name__}",
                )
            if not feed_url:
                return CandidateProbeResult(
                    valid=False,
                    reject_reason="no_declared_rss_or_atom_feed",
                )
        elif candidate.source_kind != SourceKind.FEED:
            return CandidateProbeResult(
                valid=False,
                reject_reason="no validated connector resolver for candidate kind",
            )
        def build_binding(resolved_feed_url: str) -> AcquisitionBinding:
            config = {"connection": {"rss_url": resolved_feed_url}}
            if resolved_feed_url != candidate.url:
                config["resolved_from"] = candidate.url
            return AcquisitionBinding(
                binding_id=f"binding-discovered-{canonical_hash([target_id, resolved_feed_url])[:20]}",
                target_id=target_id,
                connector_type=ConnectorType.RSS,
                config=config,
                config_hash=canonical_hash(config),
                status=BindingStatus.ACTIVE,
            )

        binding = build_binding(feed_url)
        connector = RSSConnector(
            UrllibHTTPClient(url_validator=validate_discovery_url),
            url_validator=validate_discovery_url,
        )
        try:
            result = connector.fetch(
                binding,
                limits=ConnectorLimits(max_items=5, max_bytes=1_000_000),
            )
        except Exception as exc:
            return CandidateProbeResult(
                valid=False,
                reject_reason=f"connector_probe_failed:{exc.__class__.__name__}",
            )
        retryable_as_html = result.errors and result.errors[0].code in {
            ConnectorErrorCode.UNSUPPORTED_CONTENT_TYPE,
            ConnectorErrorCode.PARSE_ERROR,
        }
        if result.status != "ok" and candidate.source_kind == SourceKind.FEED and retryable_as_html:
            try:
                discovered = discover_alternate_feed(candidate.url)
            except Exception:
                discovered = None
            if discovered and discovered != feed_url:
                feed_url = discovered
                binding = build_binding(feed_url)
                try:
                    result = connector.fetch(
                        binding,
                        limits=ConnectorLimits(max_items=5, max_bytes=1_000_000),
                    )
                except Exception as exc:
                    return CandidateProbeResult(
                        valid=False,
                        reject_reason=f"connector_probe_failed:{exc.__class__.__name__}",
                    )
        if result.status != "ok":
            reason = result.errors[0].code.value if result.errors else "connector_probe_failed"
            return CandidateProbeResult(valid=False, reject_reason=reason)
        return CandidateProbeResult(
            valid=True,
            binding=binding,
            sampled_items=len(result.items),
            useful_items=sum(bool(item.get("title") or item.get("summary")) for item in result.items),
        )

    def close(self) -> None:
        if self.runtime is not None:
            self.runtime.close()
        if self.owns_database:
            self.database.close()

    def refresh(self) -> dict[str, Any]:
        base = self.base
        base.app_dir().mkdir(parents=True, exist_ok=True)
        lock = base.acquire_lock()
        if lock["status"] != "locked":
            self.close()
            return lock
        base.request_id = lock["request_id"]
        base.workflow_run_id = base.request_id
        base.run_started_at = datetime.now().astimezone()
        base.step_results = []
        base.store_summary = None
        base.signal_diff = None
        base.adapter_summary = None
        base.source_snapshot = None
        base.resolved_sources_config = None
        base.agent_stage_status = "pending"
        base.degraded_reasons = self.degraded_reasons
        base.workflow_usage = self.usage
        run = WorkflowRun(
            run_id=base.workflow_run_id,
            status=WorkflowStatus.RUNNING,
            started_at=base.run_started_at,
            input_hash=canonical_hash(
                {
                    "user_id": base.user_id,
                    "event_ids": [event.event_id for event in self.events.list_for_user(base.user_id)],
                    "flags": self.flags.model_dump(),
                }
            ),
        )
        self.workflows.create_run(run)
        base.write_status("running", {"current_step": None, "command_results": []})
        try:
            self._step("persist_events", self._persist_events)
            self._step(
                "compile_resolve_profile",
                self._compile_resolve_profile,
                degradable=True,
            )
            self._step(
                "decide_discover_sources",
                self._decide_discover_sources,
                degradable=True,
            )
            self._step("resolve_source_snapshot", self._resolve_source_snapshot)
            self._step("collect", self._collect)
            self._step("ingest_store", self._ingest_store)
            self._step("baseline_score", self._baseline_score)
            self._step("agent_assess", self._agent_assess, degradable=True)
            self._step("validate_compose", self._validate_compose)
            self._step("publish", self._publish)
            self._step("trace", self._trace_summary)
        except Exception as exc:
            failed = run.model_copy(
                update={
                    "status": WorkflowStatus.FAILED,
                    "finished_at": datetime.now(timezone.utc),
                    "profile_id": self.profile.profile_id,
                    "source_snapshot_id": (
                        base.source_snapshot.snapshot_id if base.source_snapshot else None
                    ),
                    "degraded_reasons": tuple(self.degraded_reasons),
                    "usage": self.usage,
                }
            )
            self.workflows.update_run(failed)
            status = base.write_status(
                "failed",
                {"last_error": str(exc), "command_results": base.step_results},
            )
            base.release_lock()
            self.close()
            return status

        signal_count = len((self.final_output or {}).get("signals", []))
        partial_connector = bool(
            base.adapter_summary
            and base.adapter_summary["failed_sources"]
            + base.adapter_summary["partial_sources"]
            > 0
        )
        partial = bool(self.degraded_reasons or partial_connector)
        workflow_status = (
            WorkflowStatus.SUCCEEDED_PARTIAL if partial else WorkflowStatus.SUCCEEDED
        )
        completed = run.model_copy(
            update={
                "status": workflow_status,
                "finished_at": datetime.now(timezone.utc),
                "profile_id": self.profile.profile_id,
                "source_snapshot_id": (
                    base.source_snapshot.snapshot_id if base.source_snapshot else None
                ),
                "output_hash": canonical_hash(self.final_output or {}),
                "degraded_reasons": tuple(self.degraded_reasons),
                "usage": self.usage,
            }
        )
        self.workflows.update_run(completed)
        status_name = (
            "succeeded_partial"
            if partial
            else "succeeded" if signal_count else "succeeded_empty"
        )
        status = base.write_status(
            status_name,
            {
                "command_results": base.step_results,
                "last_successful_generated_at": (self.final_output or {}).get("generated_at"),
                "last_successful_input_run_id": (self.final_output or {}).get("input_run_id"),
            },
        )
        base.release_lock()
        self.close()
        return status

    def _step(self, name: str, callback: Any, *, degradable: bool = False) -> Any:
        base = self.base
        sequence = L4_STEP_ORDER.index(name) + 1
        started_at = datetime.now(timezone.utc)
        input_hash = canonical_hash(
            {
                "run_id": base.workflow_run_id,
                "step": name,
                "profile_id": self.profile.profile_id,
                "source_snapshot_id": (
                    base.source_snapshot.snapshot_id if base.source_snapshot else None
                ),
            }
        )
        base.write_status(
            "running", {"current_step": name, "command_results": base.step_results}
        )
        row = {"name": name, "exit_status": 0, "started_at": started_at.isoformat()}
        try:
            value = callback()
            finished_at = datetime.now(timezone.utc)
            row.update(
                {
                    "finished_at": finished_at.isoformat(),
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            base.step_results.append(row)
            self.workflows.append_trace(
                WorkflowStepTrace(
                    trace_id=f"trace-{base.workflow_run_id}-{sequence}",
                    run_id=base.workflow_run_id,
                    step_name=name,
                    sequence=sequence,
                    status=StepStatus.SUCCEEDED,
                    started_at=started_at,
                    finished_at=finished_at,
                    input_hash=input_hash,
                    output_hash=canonical_hash(value),
                    policy_version=(
                        self.ranking_service.ranking_policy.version
                        if name in {"agent_assess", "validate_compose"}
                        and self.ranking_service is not None
                        else None
                    ),
                    model_id=self._node_metadata(value).get("model_id"),
                    prompt_version=self._node_metadata(value).get(
                        "prompt_version"
                    ),
                    usage=self._trace_usage(value),
                    details=self._trace_details(value),
                )
            )
            return value
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            safe_error = f"{name} failed ({exc.__class__.__name__})"
            row.update(
                {
                    "exit_status": 1,
                    "finished_at": finished_at.isoformat(),
                    "stderr_tail": safe_error,
                }
            )
            base.step_results.append(row)
            status = StepStatus.DEGRADED if degradable else StepStatus.FAILED
            failure_audit = self._failure_node_audit(name, exc)
            self.workflows.append_trace(
                WorkflowStepTrace(
                    trace_id=f"trace-{base.workflow_run_id}-{sequence}",
                    run_id=base.workflow_run_id,
                    step_name=name,
                    sequence=sequence,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    input_hash=input_hash,
                    model_id=failure_audit.get("model_id"),
                    prompt_version=failure_audit.get("prompt_version"),
                    policy_version=failure_audit.get("policy_version"),
                    usage=dict(failure_audit.get("usage") or {}),
                    error=safe_error,
                    details=(
                        {"node_audit": failure_audit} if failure_audit else {}
                    ),
                )
            )
            if degradable:
                self.degraded_reasons.append(safe_error)
                if name == "agent_assess":
                    self.final_output = self.baseline_output
                    base.agent_stage_status = "degraded_deterministic_fallback"
                return None
            raise

    def _failure_node_audit(
        self, name: str, exc: Exception
    ) -> dict[str, Any]:
        audit: dict[str, Any] = {}
        if name == "compile_resolve_profile" and self.profile_service is not None:
            audit = dict(
                getattr(getattr(self.profile_service, "compiler", None), "last_audit", {})
                or {}
            )
        elif name == "agent_assess" and self.ranking_service is not None:
            audits = getattr(self.ranking_service, "last_agent_audits", [])
            if audits:
                audit = dict(audits[-1])
        if audit:
            audit["status"] = "error"
            audit["error_types"] = list(
                dict.fromkeys([*(audit.get("error_types") or []), exc.__class__.__name__])
            )
        return audit

    @staticmethod
    def _node_metadata(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        audit = value.get("node_audit")
        if isinstance(audit, dict):
            return audit
        if isinstance(audit, list) and audit:
            return audit[0]
        return {}

    @staticmethod
    def _trace_usage(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or "node_audit" not in value:
            return {}
        audits = value["node_audit"]
        if isinstance(audits, dict):
            return dict(audits.get("usage") or {})
        if isinstance(audits, list):
            return {
                "invocations": len(audits),
                "items": [dict(item.get("usage") or {}) for item in audits],
            }
        return {}

    @staticmethod
    def _trace_details(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            details = {
                key: value[key]
                for key in ("status", "count", "signals", "snapshot_id")
                if key in value
            }
            if "source_results" in value:
                details["connector_calls"] = value["source_results"]
            if "node_audit" in value:
                details["node_audit"] = value["node_audit"]
            for key in ("total_sources", "ok_sources", "failed_sources", "partial_sources"):
                if key in value:
                    details[key] = value[key]
            return details
        return {}

    def _persist_events(self) -> dict[str, Any]:
        events = self.events.list_for_user(self.base.user_id)
        return {"count": len(events), "event_ids": [event.event_id for event in events]}

    def _compile_resolve_profile(self) -> dict[str, Any]:
        if not self.flags.profile_enabled:
            self.profile = EffectiveProfile(
                user_id=self.base.user_id, initialized=False
            )
            self.base.profile_id = None
            return {"status": "disabled", "profile_id": None, "profile_hash": None}
        events = tuple(self.events.list_for_user(self.base.user_id))
        active = active_events(events)
        active_event_ids = tuple(event.event_id for event in active)
        previous = (
            self.profiles.get_active(self.base.user_id) if active_event_ids else None
        )
        compiled = None
        node_audit: dict[str, Any] = {
            "node": "profile_compiler",
            "status": "skipped_no_pending_events",
            "usage": {},
            "trace_event_kinds": [],
        }
        if active_event_ids and (
            previous is None or previous.based_on_event_ids != active_event_ids
        ):
            if self.profile_service is None:
                raise RuntimeError("profile compiler service is unavailable")
            try:
                compiled = self.profile_service.compile_current(self.base.user_id)
            except Exception:
                # Compilation is atomic in ProfileRepository. Resolve the last
                # active snapshot before surfacing a degradable step failure so
                # downstream discovery and ranking never lose known context.
                self.profile = self.profiles.resolve_effective_profile(
                    self.base.user_id
                )
                self.base.profile_id = self.profile.profile_id
                raise
            self.usage["profile_compiler"] = compiled.audit.usage
            node_audit = {
                "node": "profile_compiler",
                "status": "ok",
                "model_id": compiled.snapshot.model_id,
                "prompt_version": compiled.snapshot.prompt_version,
                "policy_version": compiled.snapshot.policy_version,
                "usage": compiled.audit.usage,
                "replayed": compiled.audit.replayed,
                "trace_event_kinds": [
                    event.kind for event in compiled.audit.trace_events
                ],
            }
        self.profile = self.profiles.resolve_effective_profile(self.base.user_id)
        self.base.profile_id = self.profile.profile_id
        return {
            "status": "active" if self.profile.initialized else "uninitialized",
            "profile_id": self.profile.profile_id,
            "profile_hash": self.profile.profile_hash,
            "compiled": compiled is not None,
            "pending_event_count": 0,
            "node_audit": AgentNodeAudit.model_validate(node_audit).model_dump(
                mode="json"
            ),
        }

    def _decide_discover_sources(self) -> dict[str, Any]:
        if not self.flags.source_discovery_enabled or self.discovery_service is None:
            return {"status": "disabled"}
        runs = self.discovery_repository.list_runs(self.base.user_id)
        last = runs[-1] if runs else None
        all_events = self.events.list_for_user(self.base.user_id)
        events = tuple(
            event
            for event in all_events
            if last is None or event.occurred_at > last.started_at
        )
        targets = self.sources.list_targets()
        healthy = sum(target.status.value in {"active", "probation"} for target in targets)
        due = decide_source_discovery_due(
            DiscoveryCadenceState(
                current_profile_hash=self.profile.profile_hash,
                last_profile_hash=last.profile_hash if last else None,
                last_discovery_at=last.started_at if last else None,
                event_types=tuple(event.event_type for event in events),
                active_source_coverage=(healthy / len(targets)) if targets else 0,
                unhealthy_source_count=sum(
                    target.status.value == "unhealthy" for target in targets
                ),
            )
        )
        self.discovery_result = self.discovery_service.run(
            user_id=self.base.user_id,
            profile=self.profile,
            due=due,
            previous_snapshot=self.sources.latest_snapshot(),
            events=events,
            workflow_run_id=self.base.workflow_run_id,
        )
        if self.discovery_result.run.degraded_reasons:
            self.degraded_reasons.extend(self.discovery_result.run.degraded_reasons)
        return {
            "status": self.discovery_result.run.status,
            "count": sum(item.accepted for item in self.discovery_result.decisions),
            "snapshot_id": self.discovery_result.run.output_snapshot_id,
            "node_audit": (
                self.discovery_result.run.agent_audit.model_dump(mode="json")
                if self.discovery_result.run.agent_audit
                else {
                    "node": "source_discovery",
                    "status": self.discovery_result.run.status,
                    "model_id": self.discovery_result.run.model_id,
                    "prompt_version": self.discovery_result.run.prompt_version,
                    "policy_version": self.discovery_result.run.policy_version,
                    "usage": {},
                    "trace_event_kinds": [],
                    "error_types": [],
                    "replayed": False,
                    "retry_limit": None,
                }
            ),
        }

    def _resolve_source_snapshot(self) -> dict[str, Any]:
        if self.flags.source_catalog_enabled:
            imported = self.database.execute(
                "SELECT COUNT(*) FROM source_imports"
            ).fetchone()[0]
            if imported == 0 and (self.root / "config/sources.yml").exists():
                from agentic_core.l4.migration import migrate_l4

                migrate_l4(self.root, database=self.database, dry_run=False)
            active = self.sources.get_active_snapshot(self.base.user_id)
            if active is not None and active[1]:
                snapshot = active[0]
            else:
                snapshot = self.source_catalog.create_snapshot(
                    snapshot_id=f"source-snapshot-{self.base.workflow_run_id}",
                    workflow_run_id=self.base.workflow_run_id,
                )
                self.sources.activate_snapshot(
                    snapshot.snapshot_id, scope_id=self.base.user_id, pinned=False
                )
            self.base.source_snapshot = snapshot
            self.base.resolved_sources_config = snapshot_to_sources_config(snapshot)
            return {"snapshot_id": snapshot.snapshot_id, "count": len(snapshot.sources)}
        self.base.resolved_sources_config = None
        return {"status": "legacy_yaml"}

    def _collect(self) -> dict[str, Any]:
        self.base._step_fetch_rss()
        return self.base.adapter_summary or {"count": 0}

    def _ingest_store(self) -> dict[str, Any]:
        self.base._step_ingest_adapter_output()
        canonical_path = self.root / "data/canonical-items/latest.json"
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        if self.flags.inbox_enabled:
            existing = {str(item.get("id")) for item in canonical.get("items", [])}
            for inbox_item in self.inbox.list_for_user(self.base.user_id):
                item = inbox_item.canonical_item
                if str(item.get("id")) not in existing:
                    canonical.setdefault("items", []).append(item)
                    existing.add(str(item.get("id")))
            canonical.setdefault("summary", {})["canonical_items"] = len(
                canonical.get("items", [])
            )
            self.base.write_json(canonical_path, canonical)
        self.base.store_summary = store_canonical_jsonl.run(
            canonical_path, self.root / "data/store"
        )
        return {
            "count": len(canonical.get("items", [])),
            "run_id": canonical.get("run_id"),
        }

    def _profile_view(self) -> dict[str, Any]:
        return self.base._legacy_profile_view(self.profile.fields)

    def _baseline_score(self) -> dict[str, Any]:
        canonical = json.loads(
            (self.root / "data/canonical-items/latest.json").read_text(encoding="utf-8")
        )
        rules = yaml.safe_load(
            (self.root / "config/signal-rules.yml").read_text(encoding="utf-8")
        )
        generated_at = datetime.now().astimezone().isoformat()
        self.baseline_output = build_signals.build_output(
            canonical,
            self._profile_view(),
            rules,
            generated_at=generated_at,
        )
        self.baseline_output.update(
            {
                "workflow_run_id": self.base.workflow_run_id,
                "profile_id": self.profile.profile_id,
                "profile_hash": self.profile.profile_hash,
                "profile_status": (
                    "active" if self.profile.initialized else "uninitialized"
                ),
                "source_snapshot_id": (
                    self.base.source_snapshot.snapshot_id
                    if self.base.source_snapshot
                    else None
                ),
            }
        )
        return {"signals": len(self.baseline_output["signals"])}

    def _agent_assess(self) -> dict[str, Any]:
        if not self.flags.agent_ranking_enabled or self.ranking_service is None:
            self.final_output = self.baseline_output
            self.base.agent_stage_status = "disabled"
            return {"status": "disabled", "signals": len((self.final_output or {}).get("signals", []))}
        canonical = json.loads(
            (self.root / "data/canonical-items/latest.json").read_text(encoding="utf-8")
        )
        rules = yaml.safe_load(
            (self.root / "config/signal-rules.yml").read_text(encoding="utf-8")
        )
        result = self.ranking_service.rank(
            canonical=canonical,
            profile=self._profile_view(),
            rules=rules,
            generated_at=self.baseline_output["generated_at"],
            top_n=self.baseline_output["summary"]["top_n"],
            workflow_run_id=self.base.workflow_run_id,
            profile_id=self.profile.profile_id,
            source_snapshot_id=(
                self.base.source_snapshot.snapshot_id if self.base.source_snapshot else None
            ),
        )
        self.final_output = result.output
        fallback = result.output["summary"]["fallback"]
        assessed = result.output["summary"]["assessed"]
        self.base.agent_stage_status = (
            "assessed" if assessed and not fallback else "degraded" if fallback else "no_candidates"
        )
        if fallback:
            self.degraded_reasons.append(f"agent item fallback count: {fallback}")
        audits = getattr(self.ranking_service, "last_agent_audits", [])
        self.usage["news_assessment"] = {
            "invocations": len(audits),
            "usage": [audit.get("usage", {}) for audit in audits],
        }
        return {
            "status": self.base.agent_stage_status,
            "signals": len(result.output["signals"]),
            "node_audit": audits,
        }

    def _validate_compose(self) -> dict[str, Any]:
        if self.final_output is None:
            self.final_output = self.baseline_output
        if self.final_output is None:
            raise RuntimeError("ranking produced no output")
        if self.final_output.get("input_run_id") != self.base.current_run_id:
            raise RuntimeError("Signal input_run_id does not match canonical run_id")
        for signal in self.final_output.get("signals", []):
            for required in ("id", "importance_score", "relevance_score", "total_score"):
                if required not in signal:
                    raise RuntimeError(f"signal missing required field: {required}")
        ranked: list[RankedSignal] = []
        for rank, signal in enumerate(self.final_output.get("signals", []), start=1):
            provenance_payload = signal.get("score_provenance")
            if provenance_payload is None:
                provenance = ScoreProvenance(
                    baseline_components={
                        "importance": float(signal["importance_score"]),
                        "relevance": float(signal["relevance_score"]),
                    },
                    baseline_score=float(signal["total_score"]),
                    final_score=float(signal["total_score"]),
                    policy_version="deterministic-baseline-v1",
                    fallback_reason=self.base.agent_stage_status
                    or "deterministic_baseline",
                )
            else:
                provenance = ScoreProvenance.model_validate(provenance_payload)
            ranked.append(
                RankedSignal(
                    signal_id=(
                        "ranked-signal-"
                        + canonical_hash(
                            [self.base.workflow_run_id, rank, str(signal["id"])]
                        )[:24]
                    ),
                    item_id=str(signal["id"]),
                    rank=rank,
                    score=provenance,
                    candidate_reasons=tuple(signal.get("candidate_reasons") or ()),
                    profile_id=self.profile.profile_id,
                    source_snapshot_id=(
                        self.base.source_snapshot.snapshot_id
                        if self.base.source_snapshot
                        else None
                    ),
                    workflow_run_id=self.base.workflow_run_id,
                    payload=signal,
                )
            )
        persisted = self.assessments.persist_final_ordering(ranked)
        self.usage["published_ordering_hash"] = canonical_hash(
            [(item.rank, item.item_id, item.score.final_score) for item in persisted]
        )
        self.base.write_json(self.base.temp_signals_path(), self.final_output)
        return {
            "signals": len(self.final_output.get("signals", [])),
            "ordering_hash": self.usage["published_ordering_hash"],
        }

    def _publish(self) -> dict[str, Any]:
        self.base.publish_signals()
        return {"signals": len((self.final_output or {}).get("signals", []))}

    def _trace_summary(self) -> dict[str, Any]:
        return {
            "status": "complete",
            "count": len(self.workflows.list_traces(self.base.workflow_run_id)),
        }
