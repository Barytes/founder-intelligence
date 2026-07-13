from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import os

import yaml
from fastapi.testclient import TestClient

from agentic_core.feature_flags import L4FeatureFlags, load_l4_feature_flags
from agentic_core.l4.database import Database
from agentic_core.l4.agents.profile_compiler import (
    ProfileCompiler,
    ProfileCompilerOutput,
)
from agentic_core.l4.connectors.inbox import InboxService
from agentic_core.l4.connectors.base import (
    ConnectorError,
    ConnectorErrorCode,
    ConnectorProvenance,
    ConnectorResult,
)
from agentic_core.l4.discovery import SourceCandidate
from agentic_core.l4.domain import (
    AgentAssessment,
    ContextEventType,
    EvidenceSpan,
    Explicitness,
    ProfileField,
    SourceKind,
    UserContextEvent,
    WorkflowStatus,
)
from agentic_core.l4.ranking import HybridRankingService
from agentic_core.l4.inspector import WorkflowInspector
from agentic_core.l4.repositories import (
    ContextEventRepository,
    InboxRepository,
    ProfileRepository,
    RuntimeControlRepository,
    SourceRepository,
    WorkflowRepository,
)
from agentic_core.l4.source_catalog import SourceCatalog
from agentic_core.l4.workflow import L4_STEP_ORDER, L4WorkflowRunner
from agentic_core.pipeline.runner import PipelineRunner
from web_workbench.app import create_app


NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def test_feed_candidate_mislabeled_html_uses_declared_feed_before_acceptance(
    tmp_path, monkeypatch
):
    database = Database(":memory:")
    runner = L4WorkflowRunner(
        PipelineRunner(
            root=tmp_path,
            l4_database=database,
            l4_feature_flags=L4FeatureFlags(),
        )
    )

    class FakeRSSConnector:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch(self, binding, *, limits):
            url = binding.config["connection"]["rss_url"]
            provenance = ConnectorProvenance(
                target_id=binding.target_id,
                binding_id=binding.binding_id,
                connector_type="rss",
                requested_url=url,
            )
            if url.endswith("/article"):
                return ConnectorResult(
                    status="failed",
                    errors=(
                        ConnectorError(
                            code=ConnectorErrorCode.UNSUPPORTED_CONTENT_TYPE,
                            message="text/html",
                        ),
                    ),
                    provenance=provenance,
                )
            return ConnectorResult(
                status="ok",
                items=({"title": "Useful update"},),
                provenance=provenance,
            )

    monkeypatch.setattr(
        "agentic_core.l4.workflow.discover_alternate_feed",
        lambda _url: "https://example.com/feed.xml",
    )
    monkeypatch.setattr("agentic_core.l4.workflow.RSSConnector", FakeRSSConnector)
    candidate = SourceCandidate(
        candidate_id="candidate-1",
        identity="example",
        url="https://example.com/article",
        source_kind=SourceKind.FEED,
        provider="example",
        display_name="Example",
        rationale="Agent mislabeled a page as a feed",
        query_id="query-1",
        confidence=0.8,
    )

    probe = runner._probe_candidate(candidate, "target-1")

    assert probe.valid is True
    assert probe.binding.config["connection"]["rss_url"] == "https://example.com/feed.xml"
    assert probe.useful_items == 1
    runner.close()
    database.close()


def write_yaml(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def signal_rules():
    return {
        "version": 1,
        "keyword_rules": [
            {"tag": "agent", "label": "Agent", "terms": ["agent reliability"]}
        ],
        "scoring": {
            "priority_weights": {"high": 1.2, "medium": 0.5, "low": 0},
            "source_type_weights": {"rss": 0.4, "inbox": 0},
            "recency": {
                "same_day": 0.7,
                "within_3_days": 0.4,
                "older": 0.1,
                "unknown": 0,
            },
            "clamp": {"min": 1, "max": 5},
        },
        "recommendation": {
            "top_n": 5,
            "min_relevance_score": 1,
            "max_summary_sentences": 2,
            "max_questions": 3,
            "max_risks": 2,
        },
        "filters": {"excluded_sources": [], "excluded_categories": []},
        "question_templates": [],
        "risk_templates": [],
    }


def canonical_item(item_id="item-1"):
    content = "Agent reliability improved after replay tests."
    return {
        "id": item_id,
        "source_id": "source-1",
        "source_type": "rss",
        "provider": "fixture",
        "source_name": "Fixture",
        "title": "Agent reliability update",
        "summary": content,
        "content": content,
        "link": f"https://example.com/{item_id}",
        "normalized_link": f"https://example.com/{item_id}",
        "published_at": NOW.isoformat(),
        "fetched_at": NOW.isoformat(),
        "content_hash": f"hash-{item_id}",
        "dedupe_key": f"id:{item_id}",
        "category": "technology",
        "tags": ["agent"],
        "priority": "medium",
        "quality_flags": [],
    }


class FixedAgent:
    model_id = "recorded-model"
    prompt_version = "news-assessment-agent-v1"

    def __init__(self, *, fail=False):
        self.fail = fail

    def assess(self, *, item, profile_id, profile_fields, recorded_output=None):
        if self.fail:
            raise TimeoutError("private timeout detail")
        quote = item["content"]
        return AgentAssessment(
            assessment_id=f"assessment-{item['id']}",
            item_id=item["id"],
            profile_id=profile_id,
            relevance=0.9,
            novelty=0.7,
            credibility=0.7,
            urgency=0.4,
            counter_signal=0.2,
            reasoning_summary="Evidence-backed recorded assessment.",
            evidence_spans=(
                EvidenceSpan(field="content", start=0, end=len(quote), quote=quote),
            ),
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            created_at=NOW,
        )


def setup_runner(
    tmp_path,
    *,
    ranking_fail=False,
    partial=False,
    ranking_enabled=True,
    discovery_service=None,
):
    write_yaml(tmp_path / "config/signal-rules.yml", signal_rules())
    write_yaml(tmp_path / "config/sources.yml", {"version": 1, "sources": []})
    write_yaml(tmp_path / "config/ingestion-rules.yml", {"version": 1})
    database = Database(":memory:")
    workflow_repository = WorkflowRepository(database)
    ranking = HybridRankingService(agent=FixedAgent(fail=ranking_fail))
    runner = PipelineRunner(
        root=tmp_path,
        l4_feature_flags=L4FeatureFlags(
            workflow_enabled=True,
            source_catalog_enabled=True,
            agent_ranking_enabled=ranking_enabled,
            source_discovery_enabled=discovery_service is not None,
        ),
        l4_database=database,
        source_catalog=SourceCatalog(database),
        ranking_service=ranking,
        source_discovery_service=discovery_service,
        workflow_repository=workflow_repository,
    )

    def collect():
        runner.adapter_summary = {
            "total_sources": 2 if partial else 1,
            "ok_sources": 1,
            "partial_sources": 0,
            "failed_sources": 1 if partial else 0,
            "skipped_sources": 0,
            "items": 1,
            "source_results": [],
        }

    def ingest():
        payload = {
            "run_id": "canonical-run-1",
            "contract_version": 1,
            "generated_at": NOW.isoformat(),
            "summary": {"canonical_items": 1, "dropped_items": 0},
            "items": [canonical_item()],
        }
        runner.write_json(tmp_path / "data/canonical-items/latest.json", payload)
        runner.current_run_id = payload["run_id"]

    runner._step_fetch_rss = collect
    runner._step_ingest_adapter_output = ingest
    return runner, database, workflow_repository


def test_normal_l4_workflow_uses_exact_order_and_links_all_artifacts(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)

    status = runner.refresh()

    assert status["status"] == "succeeded"
    assert [step["name"] for step in status["step_results"]] == list(L4_STEP_ORDER)
    traces = workflows.list_traces(status["workflow_run_id"])
    assert [trace.step_name for trace in traces] == list(L4_STEP_ORDER)
    assert all(trace.input_hash and trace.output_hash for trace in traces)
    agent_trace = next(trace for trace in traces if trace.step_name == "agent_assess")
    assert agent_trace.model_id == "recorded-model"
    assert agent_trace.prompt_version == "news-assessment-agent-v1"
    assert agent_trace.policy_version == "hybrid-ranking-v1"
    run = workflows.get_run(status["workflow_run_id"])
    assert run.status == WorkflowStatus.SUCCEEDED
    assert run.source_snapshot_id == status["source_snapshot_id"]
    signals = json.loads((tmp_path / "data/signals/latest.json").read_text())
    assert signals["workflow_run_id"] == status["workflow_run_id"]
    assert signals["source_snapshot_id"] == status["source_snapshot_id"]
    assert signals["signals"][0]["agent_status"] == "valid"
    assert signals["signals"][0]["score_provenance"]["policy_version"] == "hybrid-ranking-v1"
    assert status["last_successful_generated_at"] == signals["generated_at"]
    assert status["last_successful_input_run_id"] == signals["input_run_id"]
    database.close()


def test_product_default_flags_execute_complete_l4_workflow(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)
    runner.l4_feature_flags = load_l4_feature_flags({})

    status = runner.refresh()

    assert runner.l4_feature_flags.model_dump() == {
        "profile_enabled": True,
        "source_catalog_enabled": True,
        "source_discovery_enabled": True,
        "agent_ranking_enabled": True,
        "inbox_enabled": True,
        "workflow_enabled": True,
    }
    assert status["status"] in {"succeeded", "succeeded_partial"}
    assert [trace.step_name for trace in workflows.list_traces(status["workflow_run_id"])] == list(L4_STEP_ORDER)
    assert WorkflowInspector(database).replay(status["workflow_run_id"])["status"] == "replayed"
    database.close()


def test_concurrent_l4_refresh_uses_existing_pipeline_lock(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)
    runner.app_dir().mkdir(parents=True, exist_ok=True)
    runner.lock_path().write_text(
        json.dumps({"request_id": "existing", "pid": os.getpid()}),
        encoding="utf-8",
    )

    status = runner.refresh()

    assert status == {"status": "already_running", "request_id": "existing"}
    assert workflows.get_run("existing") is None
    runner.lock_path().unlink()
    database.close()


def test_partial_connector_and_agent_item_failure_publish_degraded_fallback(tmp_path):
    runner, database, workflows = setup_runner(
        tmp_path, ranking_fail=True, partial=True
    )

    status = runner.refresh()

    assert status["status"] == "succeeded_partial"
    assert status["agent_stage_status"] == "degraded"
    assert "agent item fallback count: 1" in status["degraded_reasons"]
    signals = json.loads((tmp_path / "data/signals/latest.json").read_text())
    assert signals["signals"][0]["agent_status"] == "fallback"
    assert signals["signals"][0]["total_score"] == signals["signals"][0]["score_provenance"]["baseline_score"]
    assert workflows.get_run(status["workflow_run_id"]).status == WorkflowStatus.SUCCEEDED_PARTIAL
    database.close()


def test_canonical_failure_does_not_enter_scoring_or_replace_last_success(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)
    previous = {"contract_version": 1, "signals": [{"id": "previous"}]}
    runner.write_json(runner.latest_signals_path(), previous)

    def fail_ingest():
        raise RuntimeError("canonical validation failed")

    runner._step_ingest_adapter_output = fail_ingest
    status = runner.refresh()

    assert status["status"] == "failed"
    assert json.loads(runner.latest_signals_path().read_text()) == previous
    names = [trace.step_name for trace in workflows.list_traces(status["workflow_run_id"])]
    assert names[-1] == "ingest_store"
    assert "baseline_score" not in names
    database.close()


def test_publish_failure_preserves_previous_success(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)
    previous = {"contract_version": 1, "signals": [{"id": "previous"}]}
    runner.write_json(runner.latest_signals_path(), previous)

    def fail_publish():
        raise OSError("disk unavailable")

    runner.publish_signals = fail_publish
    status = runner.refresh()

    assert status["status"] == "failed"
    assert json.loads(runner.latest_signals_path().read_text()) == previous
    assert workflows.list_traces(status["workflow_run_id"])[-1].step_name == "publish"
    database.close()


def test_ranking_flag_off_keeps_deterministic_dashboard_contract(tmp_path):
    runner, database, _workflows = setup_runner(tmp_path, ranking_enabled=False)

    status = runner.refresh()

    signals = json.loads(runner.latest_signals_path().read_text())
    assert status["agent_stage_status"] == "disabled"
    assert "importance_score" in signals["signals"][0]
    assert "score_provenance" not in signals["signals"][0]
    replay = WorkflowInspector(database).replay(status["workflow_run_id"])
    assert replay["status"] == "replayed"
    assert replay["external_calls"] == 0
    assert replay["ordering"] == [signal["id"] for signal in signals["signals"]]
    assert replay["signals"] == signals["signals"]
    database.close()


def test_successful_empty_publication_replays_as_empty_ordering(tmp_path):
    runner, database, _workflows = setup_runner(tmp_path, ranking_enabled=False)

    def ingest_empty():
        payload = {
            "run_id": "canonical-empty",
            "contract_version": 1,
            "generated_at": NOW.isoformat(),
            "summary": {"canonical_items": 0, "dropped_items": 0},
            "items": [],
        }
        runner.write_json(tmp_path / "data/canonical-items/latest.json", payload)
        runner.current_run_id = payload["run_id"]

    runner._step_ingest_adapter_output = ingest_empty
    status = runner.refresh()
    replay = WorkflowInspector(database).replay(status["workflow_run_id"])

    assert status["status"] == "succeeded_empty"
    assert replay["status"] == "replayed"
    assert replay["ordering"] == []
    assert replay["signals"] == []
    database.close()


def test_profile_resolution_failure_degrades_to_neutral_without_changing_store(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)

    class FailingProfiles:
        def resolve_effective_profile(self, _user_id):
            raise RuntimeError("profile store unavailable")

    runner.profile_repository = FailingProfiles()
    runner.l4_feature_flags = runner.l4_feature_flags.model_copy(
        update={"profile_enabled": True}
    )
    status = runner.refresh()

    assert status["status"] == "succeeded_partial"
    assert "compile_resolve_profile failed (RuntimeError)" in status["degraded_reasons"]
    assert status["profile_id"] is None
    assert workflows.get_run(status["workflow_run_id"]).profile_id is None
    database.close()


def _context_event(event_id, *, text="agent reliability"):
    return UserContextEvent(
        event_id=event_id,
        user_id="local-user",
        event_type=ContextEventType.USER_STATEMENT,
        payload={"field": "interests", "text": text},
        origin="test",
        explicitness=Explicitness.EXPLICIT,
        occurred_at=NOW,
        idempotency_key=f"test:{event_id}",
    )


def _recorded_profile_service(database, *, calls):
    events = ContextEventRepository(database)
    profiles = ProfileRepository(database)
    compiler = ProfileCompiler(
        repository=profiles,
        runtime=None,
        model_id="recorded-profile-model",
    )

    class RecordedService:
        def compile_current(self, user_id):
            calls.append(user_id)
            current = events.list_for_user(user_id)
            compiler_input = compiler.build_input(
                user_id=user_id,
                events=current,
                previous_snapshot=profiles.get_active(user_id),
            )
            return compiler.compile(
                compiler_input,
                recorded_output=ProfileCompilerOutput(
                    fields={
                        "interests": ProfileField(
                            value=[event.payload["text"] for event in current],
                            provenance_event_ids=tuple(
                                event.event_id for event in current
                            ),
                            confidence=1,
                        )
                    },
                    change_summary="Recorded profile",
                ),
            )

    return RecordedService()


def test_workflow_compiles_pending_profile_events_once(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)
    runner.l4_feature_flags = runner.l4_feature_flags.model_copy(
        update={"profile_enabled": True}
    )
    ContextEventRepository(database).append(_context_event("event-1"))
    calls = []
    runner.profile_service = _recorded_profile_service(database, calls=calls)

    first = runner.refresh()
    second = runner.refresh()

    assert calls == ["local-user"]
    assert first["profile_id"] == second["profile_id"]
    assert ProfileRepository(database).get_active("local-user").based_on_event_ids == (
        "event-1",
    )
    profile_trace = next(
        trace
        for trace in workflows.list_traces(first["workflow_run_id"])
        if trace.step_name == "compile_resolve_profile"
    )
    assert profile_trace.model_id == "recorded-profile-model"
    assert profile_trace.prompt_version == "profile-compiler-v1"
    assert profile_trace.details["node_audit"]["trace_event_kinds"] == []
    database.close()


def test_profile_compile_retry_failure_uses_previous_active_snapshot(tmp_path):
    runner, database, workflows = setup_runner(tmp_path)
    runner.l4_feature_flags = runner.l4_feature_flags.model_copy(
        update={"profile_enabled": True}
    )
    events = ContextEventRepository(database)
    events.append(_context_event("event-1", text="reliability"))
    calls = []
    recorded = _recorded_profile_service(database, calls=calls)
    first = recorded.compile_current("local-user")
    events.append(_context_event("event-2", text="evaluation"))

    class FailingService:
        def compile_current(self, _user_id):
            raise RuntimeError("model unavailable")

    runner.profile_service = FailingService()
    status = runner.refresh()

    assert status["status"] == "succeeded_partial"
    assert status["profile_id"] == first.snapshot.profile_id
    assert workflows.get_run(status["workflow_run_id"]).profile_id == first.snapshot.profile_id
    assert ProfileRepository(database).get_active("local-user").profile_id == first.snapshot.profile_id
    database.close()


def test_discovery_failure_uses_existing_catalog_snapshot(tmp_path):
    class FailingDiscovery:
        def run(self, **_kwargs):
            raise RuntimeError("search failed")

    runner, database, workflows = setup_runner(
        tmp_path, discovery_service=FailingDiscovery()
    )
    previous = runner.source_catalog.create_snapshot(snapshot_id="snapshot-before")

    status = runner.refresh()

    assert status["status"] == "succeeded_partial"
    assert "decide_discover_sources failed (RuntimeError)" in status["degraded_reasons"]
    assert status["source_snapshot_id"] == previous.snapshot_id
    assert workflows.get_run(status["workflow_run_id"]).source_snapshot_id == previous.snapshot_id
    database.close()


def test_whole_ranking_stage_failure_uses_baseline_and_marks_degraded(tmp_path):
    runner, database, _workflows = setup_runner(tmp_path)

    class BrokenRanking:
        ranking_policy = type("Policy", (), {"version": "broken-policy"})()

        def rank(self, **_kwargs):
            raise RuntimeError("ranking adapter crashed")

    runner.ranking_service = BrokenRanking()
    status = runner.refresh()

    assert status["status"] == "succeeded_partial"
    assert status["agent_stage_status"] == "degraded_deterministic_fallback"
    signals = json.loads(runner.latest_signals_path().read_text())
    assert "score_provenance" not in signals["signals"][0]
    replay = WorkflowInspector(database).replay(status["workflow_run_id"])
    assert replay["status"] == "replayed"
    assert replay["ordering"] == [signal["id"] for signal in signals["signals"]]
    assert replay["signals"] == signals["signals"]
    database.close()


def test_persistent_stage_kill_switch_disables_agent_ranking_at_run_time(tmp_path):
    runner, database, _workflows = setup_runner(tmp_path)
    RuntimeControlRepository(database).set_enabled("agent_ranking", False)

    status = runner.refresh()

    assert status["status"] == "succeeded"
    assert status["agent_stage_status"] == "disabled"
    signals = json.loads(runner.latest_signals_path().read_text())
    assert "score_provenance" not in signals["signals"][0]
    database.close()


def test_real_api_loop_context_inbox_refresh_and_hybrid_news(tmp_path):
    runner, database, _workflows = setup_runner(tmp_path)
    runner.l4_feature_flags = runner.l4_feature_flags.model_copy(
        update={"profile_enabled": True, "inbox_enabled": True}
    )
    events = ContextEventRepository(database)
    profiles = ProfileRepository(database)
    compiler = ProfileCompiler(
        repository=profiles,
        runtime=None,
        model_id="recorded-profile-model",
    )

    class RecordedProfileService:
        def __init__(self):
            self.compiler = compiler

        def compile_current(self, user_id):
            current_events = events.list_for_user(user_id)
            latest = current_events[-1]
            compiler_input = compiler.build_input(
                user_id=user_id,
                events=current_events,
                previous_snapshot=profiles.get_active(user_id),
            )
            return compiler.compile(
                compiler_input,
                recorded_output=ProfileCompilerOutput(
                    fields={
                        "interests": ProfileField(
                            value=["agent reliability"],
                            provenance_event_ids=(latest.event_id,),
                            confidence=1,
                        )
                    },
                    change_summary="Recorded explicit interest",
                ),
            )

    inbox_service = InboxService(
        inbox=InboxRepository(database),
        sources=SourceRepository(database),
        url_validator=lambda url: url,
    )
    app = create_app(
        repo_root=tmp_path,
        runner=runner,
        auto_start_rsshub=False,
        l4_feature_flags=runner.l4_feature_flags,
        l4_database=database,
        profile_service=RecordedProfileService(),
        inbox_service=inbox_service,
    )
    client = TestClient(app)
    headers = {"origin": "http://testserver"}

    context = client.post(
        "/api/context/events",
        headers=headers,
        json={
            "event_type": "user_statement",
            "payload": {"text": "I care about agent reliability"},
        },
    )
    shared = client.post(
        "/api/inbox/items",
        headers=headers,
        json={
            "url": "https://example.com/shared",
            "title": "Shared reliability note",
            "captured_content": "Agent reliability evidence from a shared article.",
        },
    )
    refreshed = client.post("/api/refresh", headers=headers, json={})

    assert context.json()["profile_status"] == "active"
    assert shared.json()["item"]["canonical_item"]["origin"] == "user_shared"
    assert refreshed.status_code == 200
    signals = client.get("/api/signals/latest").json()
    assert signals["profile_id"] == context.json()["profile"]["profile_id"]
    assert any(signal["source"]["type"] == "inbox" for signal in signals["signals"])
    assert all("score_provenance" in signal for signal in signals["signals"])
    run_id = refreshed.json()["workflow_run_id"]
    inspector = client.get(f"/api/inspector/runs/{run_id}").json()
    assert [step["step_name"] for step in inspector["timeline"]] == list(L4_STEP_ORDER)
    assert inspector["profile_events"][0]["event_id"] == context.json()["event"]["event_id"]
    assert inspector["chain_of_thought"] is None
    assert inspector["assessments"]
    assert client.post(f"/api/inspector/runs/{run_id}/replay", json={}).status_code == 403
    replay = client.post(
        f"/api/inspector/runs/{run_id}/replay", headers=headers, json={}
    ).json()
    assert replay["external_calls"] == 0
    assert replay["ordering"] == [signal["id"] for signal in signals["signals"]]

    control = client.post(
        "/api/inspector/controls/agent_ranking",
        headers=headers,
        json={"enabled": False},
    )
    assert control.json()["control"]["enabled"] is False
    rollback_profile = client.post(
        "/api/inspector/rollback/profile",
        headers=headers,
        json={"profile_id": context.json()["profile"]["profile_id"]},
    )
    assert rollback_profile.json()["status"] == "rolled_back"
    rollback_source = client.post(
        "/api/inspector/rollback/source",
        headers=headers,
        json={"snapshot_id": refreshed.json()["source_snapshot_id"]},
    )
    assert rollback_source.json()["pinned"] is True
    database.close()


def test_concurrent_first_page_requests_initialize_one_sqlite_store(tmp_path):
    write_yaml(tmp_path / "config/sources.yml", {"version": 1, "sources": [], "source_templates": {}})
    (tmp_path / "config/user-profile.yml").write_text("version: 1\n", encoding="utf-8")
    (tmp_path / "data/signals").mkdir(parents=True)
    (tmp_path / "data/signals/latest.json").write_text(
        json.dumps({"contract_version": 1, "signals": [], "summary": {}}),
        encoding="utf-8",
    )
    flags = L4FeatureFlags(profile_enabled=True, source_catalog_enabled=True)
    client = TestClient(
        create_app(
            repo_root=tmp_path,
            runner=object(),
            auto_start_rsshub=False,
            l4_feature_flags=flags,
        )
    )
    paths = [
        "/api/signals/latest",
        "/api/sources",
        "/api/profile/current",
        "/api/inspector/runs",
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(client.get, paths))

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    database = Database(tmp_path / "data/app/founder-intelligence.db")
    assert database.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 5
    database.close()
