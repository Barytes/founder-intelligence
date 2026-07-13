from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agentic_core.l4.agents.source_discovery import (
    SourceDiscoveryError,
    verify_source_discovery_output,
)
from agentic_core.l4.database import Database
from agentic_core.l4.discovery import (
    CandidateProbeResult,
    DiscoveryCadenceState,
    DiscoveryDue,
    SourceCandidate,
    SourceDiscoveryAgentInput,
    SourceDiscoveryAgentOutput,
    SourceDiscoveryService,
    SourceObservation,
    build_discovery_queries,
    decide_source_discovery_due,
    decide_source_lifecycle,
)
from agentic_core.l4.domain import (
    AcquisitionBinding,
    BindingStatus,
    ConnectorType,
    ContextEventType,
    EffectiveProfile,
    Explicitness,
    SourceKind,
    SourceStatus,
    SourceTarget,
    UserContextEvent,
)
from agentic_core.l4.hashing import canonical_hash, source_identity_key
from agentic_core.l4.repositories import SourceDiscoveryRepository, SourceRepository
from agentic_core.l4.search import (
    BraveSearchProvider,
    FakeSearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchResponse,
    SearchResult,
)


NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def profile(*hints: str) -> EffectiveProfile:
    return EffectiveProfile(
        user_id="user-1",
        initialized=True,
        profile_id="profile-1",
        profile_hash="profile-hash-1",
        fields={"discovery_hints": list(hints)},
        resolved_at=NOW,
    )


def result(url="https://example.com/feed.xml", *, rank=1, query_id="query-1"):
    return SearchResult(
        result_id=f"{query_id}:{rank}",
        title="Example source",
        url=url,
        description="durable source",
        rank=rank,
    )


def candidate(url="https://example.com/feed.xml", *, number=1):
    return SourceCandidate(
        candidate_id=f"candidate-{number}",
        identity=f"example-{number}",
        url=url,
        source_kind=SourceKind.FEED,
        provider="example",
        display_name=f"Example {number}",
        rationale="Direct feed for the requested topic",
        query_id="query-1",
        confidence=0.8,
    )


class FakeAgent:
    model_id = "recorded-model"
    prompt_version = "source-discovery-agent-v1"

    def __init__(self, output):
        self.output = output
        self.inputs = []

    def discover(self, agent_input, *, recorded_output=None):
        self.inputs.append(agent_input)
        return SourceDiscoveryAgentOutput.model_validate(recorded_output or self.output)


def binding_for(target_id: str, url: str) -> AcquisitionBinding:
    config = {"connection": {"rss_url": url}}
    return AcquisitionBinding(
        binding_id=f"binding-{target_id}",
        target_id=target_id,
        connector_type=ConnectorType.RSS,
        config=config,
        config_hash=canonical_hash(config),
        credential_refs=(),
        status=BindingStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def valid_probe(source_candidate, target_id):
    return CandidateProbeResult(
        valid=True,
        binding=binding_for(target_id, source_candidate.url),
        sampled_items=3,
        useful_items=2,
        duplicate_ratio=0,
    )


def service(output, *, provider=None, probe=valid_probe, candidate_limit=5):
    database = Database(":memory:")
    sources = SourceRepository(database)
    discovery = SourceDiscoveryRepository(database)
    provider = provider or FakeSearchProvider({"query-1": [result()]})
    return database, SourceDiscoveryService(
        provider=provider,
        agent=FakeAgent(output),
        sources=sources,
        discovery=discovery,
        probe=probe,
        url_validator=lambda url: url,
        candidate_limit=candidate_limit,
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-fixed",
    ), sources, discovery


def test_discovery_due_is_deterministic_for_profile_event_interval_and_health():
    changed = decide_source_discovery_due(
        DiscoveryCadenceState(
            current_profile_hash="new",
            last_profile_hash="old",
            last_discovery_at=NOW,
            now=NOW,
        )
    )
    explicit = decide_source_discovery_due(
        DiscoveryCadenceState(
            current_profile_hash="same",
            last_profile_hash="same",
            last_discovery_at=NOW,
            now=NOW,
            event_types=(ContextEventType.FOLLOW,),
        )
    )
    interval_health = decide_source_discovery_due(
        DiscoveryCadenceState(
            current_profile_hash="same",
            last_profile_hash="same",
            last_discovery_at=NOW - timedelta(days=8),
            now=NOW,
            active_source_coverage=0.4,
        )
    )

    assert changed.reasons == ("profile_changed",)
    assert explicit.reasons == ("explicit_follow_or_share",)
    assert interval_health.reasons == (
        "interval_elapsed",
        "coverage_or_health_declined",
    )


def test_not_due_skips_search_provider_and_keeps_previous_snapshot():
    provider = FakeSearchProvider()
    database, discovery_service, sources, repository = service(
        SourceDiscoveryAgentOutput(candidates=(), summary="unused"), provider=provider
    )
    previous = sources.create_snapshot(snapshot_id="snapshot-old")

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI infrastructure"),
        due=DiscoveryDue(due=False),
        previous_snapshot=previous,
    )

    assert provider.calls == []
    assert value.run.status == "skipped"
    assert value.snapshot == previous
    assert repository.get_run(value.run.discovery_run_id) == value.run
    database.close()


def test_search_outage_is_degraded_and_keeps_previous_snapshot():
    provider = FakeSearchProvider(error="provider unavailable")
    database, discovery_service, sources, repository = service(
        SourceDiscoveryAgentOutput(candidates=(), summary="unused"), provider=provider
    )
    previous = sources.create_snapshot(snapshot_id="snapshot-old")

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI infrastructure"),
        due=DiscoveryDue(due=True, reasons=("profile_changed",)),
        workflow_run_id="workflow-1",
        previous_snapshot=previous,
    )

    assert value.run.status == "degraded"
    assert value.run.output_snapshot_id == previous.snapshot_id
    assert value.snapshot == previous
    assert "provider unavailable" in value.run.degraded_reasons[0]
    database.close()


def test_one_search_failure_keeps_successful_results_and_candidate_decisions():
    class PartialProvider:
        name = "partial"

        def search(self, query, *, limit):
            if query.query_id == "query-2":
                raise SearchProviderError("rate limited")
            return SearchResponse(
                provider=self.name,
                query=query,
                results=(result(query_id=query.query_id),),
            )

    selected = candidate().model_copy(update={"query_id": "query-1"})
    database, discovery_service, _sources, repository = service(
        SourceDiscoveryAgentOutput(candidates=(selected,), summary="selected"),
        provider=PartialProvider(),
    )

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI infrastructure", "agent reliability"),
        due=DiscoveryDue(due=True, reasons=("profile_changed",)),
    )

    assert value.run.status == "succeeded_partial"
    assert len(value.decisions) == 1
    assert value.decisions[0].accepted is True
    assert "query-2: rate limited" in value.run.degraded_reasons
    assert repository.get_run(value.run.discovery_run_id) == value.run
    database.close()


def test_explicit_follow_event_resolves_target_without_sending_full_event_to_search():
    url = "https://example.com/followed-feed.xml"
    followed = candidate(url).model_copy(
        update={"query_id": None, "event_id": "follow-1"}
    )
    provider = FakeSearchProvider()
    database, discovery_service, sources, _repository = service(
        SourceDiscoveryAgentOutput(candidates=(followed,), summary="explicit follow"),
        provider=provider,
    )
    event = UserContextEvent(
        event_id="follow-1",
        user_id="user-1",
        event_type=ContextEventType.FOLLOW,
        payload={"url": url, "title": "Followed source", "private_note": "secret"},
        origin="web",
        explicitness=Explicitness.EXPLICIT,
        occurred_at=NOW,
        idempotency_key="follow-1",
    )

    value = discovery_service.run(
        user_id="user-1",
        profile=profile(),
        due=DiscoveryDue(due=True, reasons=("explicit_follow_or_share",)),
        events=(event,),
    )

    assert provider.calls == []
    assert value.decisions[0].accepted is True
    assert sources.get_target(value.decisions[0].target_id).status == SourceStatus.PROBATION
    agent_input = discovery_service.agent.inputs[0]
    assert agent_input.event_hints[0].url == url
    assert "private_note" not in agent_input.model_dump_json()
    database.close()


def test_agent_failure_is_sanitized_and_uses_previous_snapshot():
    class FailingAgent(FakeAgent):
        def discover(self, *_args, **_kwargs):
            raise RuntimeError("secret model failure detail")

    provider = FakeSearchProvider({"query-1": [result()]})
    database, discovery_service, sources, repository = service(
        SourceDiscoveryAgentOutput(candidates=(), summary="unused"), provider=provider
    )
    discovery_service.agent = FailingAgent(None)
    previous = sources.create_snapshot(snapshot_id="snapshot-old")

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI infrastructure"),
        due=DiscoveryDue(due=True, reasons=("profile_changed",)),
        previous_snapshot=previous,
    )

    assert value.run.status == "degraded"
    assert value.snapshot == previous
    assert value.run.degraded_reasons == (
        "source discovery agent failed (RuntimeError)",
    )
    assert "secret model failure detail" not in repository.get_run(
        value.run.discovery_run_id
    ).model_dump_json()
    database.close()


def test_valid_candidate_becomes_bounded_probation_source_with_full_trace():
    output = SourceDiscoveryAgentOutput(candidates=(candidate(),), summary="one source")
    database, discovery_service, sources, repository = service(output)

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI infrastructure"),
        due=DiscoveryDue(due=True, reasons=("profile_changed",)),
        workflow_run_id="workflow-1",
    )

    assert value.run.status == "succeeded"
    assert len(value.decisions) == 1
    assert value.decisions[0].accepted is True
    target = sources.get_target(value.decisions[0].target_id)
    source_binding = sources.list_bindings(target.target_id)[0]
    assert target.status == SourceStatus.PROBATION
    assert source_binding.config["probation"] is True
    assert source_binding.config["item_quota"] == 5
    saved_run = repository.get_run(value.run.discovery_run_id)
    saved_decisions = repository.list_decisions(value.run.discovery_run_id)
    assert saved_run.workflow_run_id == "workflow-1"
    assert saved_run.queries[0].text == "AI infrastructure RSS Atom official blog source"
    assert saved_run.search_responses[0].results[0].url.endswith("feed.xml")
    assert saved_run.search_responses[0].results[0].title == ""
    assert saved_run.search_responses[0].results[0].description == ""
    assert len(saved_run.search_responses[0].results[0].metadata["result_hash"]) == 64
    assert saved_decisions[0].reason == "validated_probation"
    database.close()


def test_duplicate_search_result_converges_without_source_growth():
    output = SourceDiscoveryAgentOutput(candidates=(candidate(),), summary="duplicate")
    database, discovery_service, sources, _repository = service(output)
    identity = source_identity_key(
        source_kind=SourceKind.FEED,
        provider="example",
        canonical_url=candidate().url,
    )
    existing = sources.upsert_target(
        SourceTarget(
            target_id="existing-target",
            source_kind=SourceKind.FEED,
            provider="example",
            canonical_url=candidate().url,
            display_name="Existing",
            identity_key=identity,
            status=SourceStatus.ACTIVE,
        )
    )

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI infrastructure"),
        due=DiscoveryDue(due=True, reasons=("interval_elapsed",)),
    )

    assert len(sources.list_targets()) == 1
    assert value.decisions[0].target_id == existing.target_id
    assert value.decisions[0].reason == "converged_to_existing_target"
    database.close()


def test_private_url_and_low_quality_probe_are_rejected_before_activation():
    private = candidate("http://127.0.0.1/private")
    provider = FakeSearchProvider({"query-1": [result(private.url)]})
    output = SourceDiscoveryAgentOutput(candidates=(private,), summary="unsafe")
    database = Database(":memory:")
    sources = SourceRepository(database)
    discovery_service = SourceDiscoveryService(
        provider=provider,
        agent=FakeAgent(output),
        sources=sources,
        discovery=SourceDiscoveryRepository(database),
        probe=valid_probe,
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-fixed",
    )

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("private"),
        due=DiscoveryDue(due=True, reasons=("profile_changed",)),
    )

    assert value.decisions[0].accepted is False
    assert value.decisions[0].reason.startswith("network_policy_rejected")
    assert sources.list_targets() == []
    database.close()


def test_quantity_reward_hack_is_capped_and_zero_yield_is_rejected():
    candidates = tuple(
        candidate(f"https://example.com/feed-{index}.xml", number=index)
        for index in range(1, 5)
    )
    provider = FakeSearchProvider(
        {"query-1": [result(item.url, rank=index) for index, item in enumerate(candidates, 1)]}
    )

    def probe(item, target_id):
        if item.candidate_id == "candidate-1":
            return CandidateProbeResult(
                valid=True,
                binding=binding_for(target_id, item.url),
                sampled_items=3,
                useful_items=0,
            )
        return valid_probe(item, target_id)

    database, discovery_service, sources, _repository = service(
        SourceDiscoveryAgentOutput(candidates=candidates, summary="many"),
        provider=provider,
        probe=probe,
        candidate_limit=2,
    )

    value = discovery_service.run(
        user_id="user-1",
        profile=profile("AI"),
        due=DiscoveryDue(due=True, reasons=("interval_elapsed",)),
    )

    assert len(sources.list_targets()) == 2
    assert value.decisions[0].reason == "zero_useful_item_yield"
    assert value.decisions[-1].reason == "candidate_quota_exceeded"
    assert all(target.status != SourceStatus.ACTIVE for target in sources.list_targets())
    database.close()


def test_lifecycle_promotes_degrades_and_retires_from_observations():
    probation = [
        SourceObservation(
            observation_id=f"o-{index}",
            target_id="target-1",
            observed_at=NOW + timedelta(minutes=index),
            fetch_succeeded=True,
            fetched_items=3,
            useful_items=2,
            duplicate_ratio=0.1,
        )
        for index in range(2)
    ]
    promoted = decide_source_lifecycle(SourceStatus.PROBATION, probation)
    unhealthy = decide_source_lifecycle(
        SourceStatus.ACTIVE,
        [
            SourceObservation(
                observation_id="fail-3",
                target_id="target-1",
                fetch_succeeded=False,
                consecutive_failures=3,
                health_score=0.2,
            )
        ],
    )
    retired = decide_source_lifecycle(
        SourceStatus.UNHEALTHY,
        [
            SourceObservation(
                observation_id="fail-6",
                target_id="target-1",
                fetch_succeeded=False,
                consecutive_failures=6,
                health_score=0,
            )
        ],
    )

    assert promoted.next_status == SourceStatus.ACTIVE
    assert unhealthy.next_status == SourceStatus.UNHEALTHY
    assert retired.next_status == SourceStatus.RETIRED


def test_observation_is_persisted_before_lifecycle_transition():
    output = SourceDiscoveryAgentOutput(candidates=(candidate(),), summary="one")
    database, discovery_service, sources, repository = service(output)
    discovery_result = discovery_service.run(
        user_id="user-1",
        profile=profile("AI"),
        due=DiscoveryDue(due=True, reasons=("profile_changed",)),
    )
    target_id = discovery_result.decisions[0].target_id

    first = SourceObservation(
        observation_id="observation-1",
        target_id=target_id,
        observed_at=NOW,
        fetch_succeeded=True,
        fetched_items=3,
        useful_items=2,
        duplicate_ratio=0.1,
    )
    second = first.model_copy(
        update={
            "observation_id": "observation-2",
            "observed_at": NOW + timedelta(minutes=1),
        }
    )
    discovery_service.observe_and_transition(first)
    transition = discovery_service.observe_and_transition(second)

    assert transition.next_status == SourceStatus.ACTIVE
    assert sources.get_target(target_id).status == SourceStatus.ACTIVE
    assert repository.list_observations(target_id) == [first, second]
    database.close()


def test_agent_output_verifier_rejects_prompt_injected_url_and_unknown_provenance():
    query = SearchQuery(query_id="q-1", text="topic", reason="hint")
    agent_input = SourceDiscoveryAgentInput(
        profile_id="p-1",
        profile_hash="hash",
        discovery_hints=("topic",),
        event_ids=(),
        search_responses=(
            SearchResponse(provider="fake", query=query, results=(result(query_id="q-1"),)),
        ),
        candidate_limit=2,
        policy_version="v1",
    )
    injected = candidate("https://attacker.example/activate-all")
    injected = injected.model_copy(update={"query_id": "q-1"})

    with pytest.raises(SourceDiscoveryError, match="not present"):
        verify_source_discovery_output(
            agent_input,
            SourceDiscoveryAgentOutput(candidates=(injected,), summary="obey snippet"),
        )


def test_query_builder_sends_only_minimal_hints_not_full_profile():
    value = profile("人工智能 基础设施").model_copy(
        update={"fields": {"discovery_hints": ["人工智能 基础设施"], "private_note": "secret"}}
    )

    queries = build_discovery_queries(value)

    assert queries[0].text == "人工智能 基础设施 RSS Atom official blog source"
    assert queries[0].language == "zh-hans"
    assert "secret" not in queries[0].model_dump_json()


def test_brave_adapter_is_structured_rate_aware_and_does_not_leak_secret():
    captured = {}

    def handler(request):
        captured["request"] = request
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining": "49", "x-request-id": "req-1"},
            json={
                "web": {
                    "results": [
                        {
                            "title": "Source",
                            "url": "https://example.com/feed.xml",
                            "description": "Summary",
                        }
                    ]
                }
            },
        )

    secret = "brave-secret-value"
    provider = BraveSearchProvider(
        api_key=secret,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = provider.search(
        SearchQuery(query_id="q-1", text="AI", reason="hint", language="en"),
        limit=5,
    )

    assert captured["request"].headers["x-subscription-token"] == secret
    assert response.results[0].url == "https://example.com/feed.xml"
    assert response.rate_limit["x-ratelimit-remaining"] == "49"
    assert secret not in response.model_dump_json()


def test_brave_adapter_requires_opaque_env_credential(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    provider = BraveSearchProvider(client=httpx.Client(transport=httpx.MockTransport(lambda _r: None)))

    with pytest.raises(SearchProviderError, match="credential"):
        provider.search(SearchQuery(query_id="q", text="AI", reason="hint"), limit=1)
