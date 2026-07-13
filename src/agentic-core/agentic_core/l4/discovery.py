from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentic_core.l4.connectors.base import NetworkPolicyError, validate_public_url
from agentic_core.l4.domain import (
    AcquisitionBinding,
    AgentNodeAudit,
    BindingStatus,
    ContextEventType,
    EffectiveProfile,
    ResolvedSourceSnapshot,
    SourceKind,
    SourceStatus,
    SourceTarget,
    UserContextEvent,
)
from agentic_core.l4.hashing import canonical_hash, normalize_url, source_identity_key
from agentic_core.l4.repositories import SourceDiscoveryRepository, SourceRepository
from agentic_core.l4.search import (
    SearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchResponse,
    SearchResult,
)


class DiscoveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryCadenceState(DiscoveryContract):
    current_profile_hash: str | None = None
    last_profile_hash: str | None = None
    last_discovery_at: datetime | None = None
    now: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    interval: timedelta = timedelta(days=7)
    event_types: tuple[ContextEventType, ...] = ()
    active_source_coverage: float = Field(default=1, ge=0, le=1)
    unhealthy_source_count: int = Field(default=0, ge=0)


class DiscoveryDue(DiscoveryContract):
    due: bool
    reasons: tuple[str, ...] = ()


def decide_source_discovery_due(state: DiscoveryCadenceState) -> DiscoveryDue:
    reasons: list[str] = []
    if (
        state.current_profile_hash
        and state.current_profile_hash != state.last_profile_hash
    ):
        reasons.append("profile_changed")
    if any(
        event in {ContextEventType.FOLLOW, ContextEventType.SHARED_CONTENT}
        for event in state.event_types
    ):
        reasons.append("explicit_follow_or_share")
    if state.last_discovery_at is None or state.now - state.last_discovery_at >= state.interval:
        reasons.append("interval_elapsed")
    if state.active_source_coverage < 0.6 or state.unhealthy_source_count > 0:
        reasons.append("coverage_or_health_declined")
    return DiscoveryDue(due=bool(reasons), reasons=tuple(reasons))


class SourceCandidate(DiscoveryContract):
    candidate_id: str
    identity: str
    url: str
    source_kind: SourceKind
    provider: str
    display_name: str
    rationale: str
    query_id: str | None = None
    event_id: str | None = None
    confidence: float = Field(ge=0, le=1)


class DiscoveryEventHint(DiscoveryContract):
    event_id: str
    event_type: ContextEventType
    url: str | None = None
    label: str | None = None


class SourceDiscoveryAgentInput(DiscoveryContract):
    profile_id: str | None
    profile_hash: str | None
    discovery_hints: tuple[str, ...]
    event_ids: tuple[str, ...]
    event_hints: tuple[DiscoveryEventHint, ...] = ()
    search_responses: tuple[SearchResponse, ...]
    candidate_limit: int = Field(ge=1, le=50)
    policy_version: str


class SourceDiscoveryAgentOutput(DiscoveryContract):
    candidates: tuple[SourceCandidate, ...]
    summary: str


class SourceDiscoveryAgent(Protocol):
    model_id: str
    prompt_version: str

    def discover(
        self,
        agent_input: SourceDiscoveryAgentInput,
        *,
        recorded_output: SourceDiscoveryAgentOutput | dict[str, Any] | None = None,
    ) -> SourceDiscoveryAgentOutput: ...


class CandidateProbeResult(DiscoveryContract):
    valid: bool
    binding: AcquisitionBinding | None = None
    sampled_items: int = Field(default=0, ge=0)
    useful_items: int = Field(default=0, ge=0)
    duplicate_ratio: float = Field(default=0, ge=0, le=1)
    reject_reason: str | None = None


class SourceCandidateDecision(DiscoveryContract):
    decision_id: str
    discovery_run_id: str
    candidate: SourceCandidate
    accepted: bool
    target_id: str | None = None
    reason: str
    probe: CandidateProbeResult | None = None


class SourceDiscoveryRun(DiscoveryContract):
    discovery_run_id: str
    workflow_run_id: str | None = None
    user_id: str
    status: Literal["succeeded", "succeeded_partial", "degraded", "skipped"]
    profile_hash: str | None = None
    due_reasons: tuple[str, ...]
    started_at: datetime
    finished_at: datetime
    provider: str | None = None
    queries: tuple[SearchQuery, ...] = ()
    search_responses: tuple[SearchResponse, ...] = ()
    candidate_decision_ids: tuple[str, ...] = ()
    previous_snapshot_id: str | None = None
    output_snapshot_id: str | None = None
    degraded_reasons: tuple[str, ...] = ()
    model_id: str | None = None
    prompt_version: str | None = None
    policy_version: str = "source-discovery-v1"
    agent_audit: AgentNodeAudit | None = None


def retained_search_responses(
    responses: Sequence[SearchResponse],
) -> tuple[SearchResponse, ...]:
    """Provider-rights-safe record: query/request identity and result URLs only."""
    return tuple(
        response.model_copy(
            update={
                "results": tuple(
                    SearchResult(
                        result_id=result.result_id,
                        title="",
                        url=result.url,
                        description="",
                        rank=result.rank,
                        metadata={"result_hash": canonical_hash(result)},
                    )
                    for result in response.results
                ),
                "rate_limit": {},
            }
        )
        for response in responses
    )


class SourceDiscoveryResult(DiscoveryContract):
    run: SourceDiscoveryRun
    decisions: tuple[SourceCandidateDecision, ...]
    snapshot: ResolvedSourceSnapshot | None = None


class SourceObservation(DiscoveryContract):
    observation_id: str
    target_id: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fetch_succeeded: bool
    fetched_items: int = Field(default=0, ge=0)
    useful_items: int = Field(default=0, ge=0)
    duplicate_ratio: float = Field(default=0, ge=0, le=1)
    consecutive_failures: int = Field(default=0, ge=0)
    health_score: float = Field(default=1, ge=0, le=1)
    reason: str = "scheduled_observation"


class SourceLifecycleDecision(DiscoveryContract):
    previous_status: SourceStatus
    next_status: SourceStatus
    reason: str


def decide_source_lifecycle(
    status: SourceStatus, observations: Sequence[SourceObservation]
) -> SourceLifecycleDecision:
    recent = tuple(sorted(observations, key=lambda item: item.observed_at))[-6:]
    if not recent:
        return SourceLifecycleDecision(
            previous_status=status, next_status=status, reason="insufficient_observations"
        )
    total_useful = sum(item.useful_items for item in recent)
    successful_samples = sum(item.fetch_succeeded for item in recent)
    mean_duplicate = sum(item.duplicate_ratio for item in recent) / len(recent)
    latest = recent[-1]
    if status == SourceStatus.PROBATION:
        if successful_samples >= 2 and total_useful >= 3 and mean_duplicate <= 0.5:
            return SourceLifecycleDecision(
                previous_status=status,
                next_status=SourceStatus.ACTIVE,
                reason="probation_quality_threshold_met",
            )
        if len(recent) >= 3 and total_useful == 0:
            return SourceLifecycleDecision(
                previous_status=status,
                next_status=SourceStatus.REJECTED,
                reason="probation_zero_useful_yield",
            )
    if status == SourceStatus.ACTIVE and (
        latest.consecutive_failures >= 3 or latest.health_score < 0.4
    ):
        return SourceLifecycleDecision(
            previous_status=status,
            next_status=SourceStatus.UNHEALTHY,
            reason="health_threshold_failed",
        )
    if status == SourceStatus.UNHEALTHY:
        if latest.consecutive_failures >= 6:
            return SourceLifecycleDecision(
                previous_status=status,
                next_status=SourceStatus.RETIRED,
                reason="persistent_failure_threshold_met",
            )
        if latest.fetch_succeeded and latest.health_score >= 0.7:
            return SourceLifecycleDecision(
                previous_status=status,
                next_status=SourceStatus.PAUSED,
                reason="recovered_pending_manual_resume",
            )
    return SourceLifecycleDecision(
        previous_status=status, next_status=status, reason="threshold_not_met"
    )


def _hint_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_hint_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_hint_strings(item))
        return result
    return []


def build_discovery_queries(
    profile: EffectiveProfile,
    *,
    limit: int = 3,
) -> tuple[SearchQuery, ...]:
    raw_hints: list[str] = []
    for field in ("discovery_hints", "watch_entities", "interests"):
        raw_hints.extend(_hint_strings(profile.fields.get(field)))
    seen: set[str] = set()
    queries: list[SearchQuery] = []
    for hint in raw_hints:
        normalized = " ".join(hint.split())[:300]
        if not normalized or normalized.casefold() in seen:
            continue
        seen.add(normalized.casefold())
        search_text = f"{normalized} RSS Atom official blog source"
        queries.append(
            SearchQuery(
                query_id=f"query-{len(queries) + 1}",
                text=search_text,
                reason="effective_profile_feed_discovery_hint",
                language="zh-hans" if any("\u4e00" <= char <= "\u9fff" for char in normalized) else "en",
            )
        )
        if len(queries) >= limit:
            break
    return tuple(queries)


def build_discovery_event_hints(
    events: Sequence[UserContextEvent],
) -> tuple[DiscoveryEventHint, ...]:
    hints: list[DiscoveryEventHint] = []
    for event in events:
        if event.event_type not in {ContextEventType.FOLLOW, ContextEventType.SHARED_CONTENT}:
            continue
        url = event.payload.get("url")
        if not isinstance(url, str) or not url.strip():
            url = None
        label = next(
            (
                event.payload.get(key)
                for key in ("title", "entity", "source", "text")
                if isinstance(event.payload.get(key), str) and event.payload.get(key).strip()
            ),
            None,
        )
        hints.append(
            DiscoveryEventHint(
                event_id=event.event_id,
                event_type=event.event_type,
                url=url,
                label=label[:300] if label else None,
            )
        )
    return tuple(hints)


class SourceDiscoveryService:
    def __init__(
        self,
        *,
        provider: SearchProvider,
        agent: SourceDiscoveryAgent,
        sources: SourceRepository,
        discovery: SourceDiscoveryRepository,
        probe: Callable[[SourceCandidate, str], CandidateProbeResult],
        url_validator: Callable[[str], str] = validate_public_url,
        candidate_limit: int = 5,
        per_query_limit: int = 10,
        probation_item_quota: int = 5,
        policy_version: str = "source-discovery-v1",
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[str], str] = lambda prefix: f"{prefix}-{uuid4()}",
    ):
        self.provider = provider
        self.agent = agent
        self.sources = sources
        self.discovery = discovery
        self.probe = probe
        self.url_validator = url_validator
        self.candidate_limit = candidate_limit
        self.per_query_limit = per_query_limit
        self.probation_item_quota = probation_item_quota
        self.policy_version = policy_version
        self.clock = clock
        self.id_factory = id_factory

    def run(
        self,
        *,
        user_id: str,
        profile: EffectiveProfile,
        due: DiscoveryDue,
        previous_snapshot: ResolvedSourceSnapshot | None = None,
        events: Sequence[UserContextEvent] = (),
        recorded_output: SourceDiscoveryAgentOutput | dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
    ) -> SourceDiscoveryResult:
        run_id = self.id_factory("discovery")
        started_at = self.clock()
        if not due.due:
            run = SourceDiscoveryRun(
                discovery_run_id=run_id,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                status="skipped",
                profile_hash=profile.profile_hash,
                due_reasons=(),
                started_at=started_at,
                finished_at=self.clock(),
                previous_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                output_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                policy_version=self.policy_version,
            )
            self.discovery.append_run(run, ())
            return SourceDiscoveryResult(run=run, decisions=(), snapshot=previous_snapshot)

        queries = build_discovery_queries(profile)
        responses: list[SearchResponse] = []
        provider_errors: list[str] = []
        for query in queries:
            try:
                responses.append(self.provider.search(query, limit=self.per_query_limit))
            except SearchProviderError as exc:
                provider_errors.append(f"{query.query_id}: {exc}")
        if provider_errors and not responses:
            run = SourceDiscoveryRun(
                discovery_run_id=run_id,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                status="degraded",
                profile_hash=profile.profile_hash,
                due_reasons=due.reasons,
                started_at=started_at,
                finished_at=self.clock(),
                provider=self.provider.name,
                queries=queries,
                search_responses=retained_search_responses(responses),
                previous_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                output_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                degraded_reasons=tuple(provider_errors),
                policy_version=self.policy_version,
            )
            self.discovery.append_run(run, ())
            return SourceDiscoveryResult(run=run, decisions=(), snapshot=previous_snapshot)

        hints = tuple(query.text for query in queries)
        event_hints = build_discovery_event_hints(events)
        if not responses and not event_hints:
            snapshot = self.sources.create_snapshot(
                snapshot_id=self.id_factory("source-snapshot")
            )
            run = SourceDiscoveryRun(
                discovery_run_id=run_id,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                status="succeeded",
                profile_hash=profile.profile_hash,
                due_reasons=due.reasons,
                started_at=started_at,
                finished_at=self.clock(),
                provider=self.provider.name,
                queries=queries,
                search_responses=(),
                previous_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                output_snapshot_id=snapshot.snapshot_id,
                model_id=self.agent.model_id,
                prompt_version=self.agent.prompt_version,
                policy_version=self.policy_version,
            )
            self.discovery.append_run(run, ())
            return SourceDiscoveryResult(run=run, decisions=(), snapshot=snapshot)
        agent_input = SourceDiscoveryAgentInput(
            profile_id=profile.profile_id,
            profile_hash=profile.profile_hash,
            discovery_hints=hints,
            event_ids=tuple(event.event_id for event in events),
            event_hints=event_hints,
            search_responses=tuple(responses),
            candidate_limit=self.candidate_limit,
            policy_version=self.policy_version,
        )
        try:
            output = self.agent.discover(agent_input, recorded_output=recorded_output)
        except Exception as exc:
            run = SourceDiscoveryRun(
                discovery_run_id=run_id,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
                status="degraded",
                profile_hash=profile.profile_hash,
                due_reasons=due.reasons,
                started_at=started_at,
                finished_at=self.clock(),
                provider=self.provider.name,
                queries=queries,
                search_responses=retained_search_responses(responses),
                previous_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                output_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
                degraded_reasons=tuple(provider_errors)
                + (f"source discovery agent failed ({exc.__class__.__name__})",),
                model_id=self.agent.model_id,
                prompt_version=self.agent.prompt_version,
                policy_version=self.policy_version,
                agent_audit={
                    "node": "source_discovery",
                    "model_id": self.agent.model_id,
                    "prompt_version": self.agent.prompt_version,
                    **getattr(self.agent, "last_audit", {}),
                    "status": "error",
                    "error_types": [exc.__class__.__name__],
                },
            )
            self.discovery.append_run(run, ())
            return SourceDiscoveryResult(run=run, decisions=(), snapshot=previous_snapshot)
        result_urls = {
            normalize_url(result.url): result
            for response in responses
            for result in response.results
        }
        event_urls = {
            normalize_url(hint.url)
            for hint in event_hints
            if hint.url is not None
        }
        decisions: list[SourceCandidateDecision] = []
        accepted_count = 0
        seen_identities: set[str] = set()
        for candidate in output.candidates:
            reason: str | None = None
            normalized_url: str | None = None
            identity_key: str | None = None
            if accepted_count >= self.candidate_limit:
                reason = "candidate_quota_exceeded"
            else:
                try:
                    normalized_url = normalize_url(candidate.url)
                    self.url_validator(normalized_url)
                except (ValueError, NetworkPolicyError) as exc:
                    reason = f"network_policy_rejected:{exc}"
            if reason is None and normalized_url not in set(result_urls) | event_urls:
                reason = "candidate_url_not_in_search_or_explicit_event"
            if reason is None:
                identity_key = source_identity_key(
                    source_kind=candidate.source_kind,
                    provider=candidate.provider,
                    canonical_url=normalized_url,
                )
                if identity_key in seen_identities:
                    reason = "duplicate_candidate"
                seen_identities.add(identity_key)
            existing = self.sources.find_target_by_identity(identity_key) if identity_key else None
            if reason is None and existing is not None:
                reason = "converged_to_existing_target"
            probe_result: CandidateProbeResult | None = None
            target_id: str | None = existing.target_id if existing else None
            if reason is None and normalized_url and identity_key:
                target_id = f"target-{identity_key[:20]}"
                probe_result = self.probe(candidate, target_id)
                if not probe_result.valid or probe_result.binding is None:
                    reason = probe_result.reject_reason or "connector_probe_failed"
                elif probe_result.useful_items <= 0:
                    reason = "zero_useful_item_yield"
                elif probe_result.duplicate_ratio > 0.8:
                    reason = "duplicate_ratio_too_high"
            accepted = reason is None
            if accepted and normalized_url and identity_key and target_id and probe_result:
                target = SourceTarget(
                    target_id=target_id,
                    source_kind=candidate.source_kind,
                    provider=candidate.provider,
                    canonical_url=normalized_url,
                    display_name=candidate.display_name,
                    identity_key=identity_key,
                    status=SourceStatus.PROBATION,
                    metadata={
                        "discovery_run_id": run_id,
                        "candidate_id": candidate.candidate_id,
                        "rationale": candidate.rationale,
                    },
                )
                saved = self.sources.upsert_target(target, reason="source_discovery_probation")
                binding = probe_result.binding.model_copy(
                    update={
                        "target_id": saved.target_id,
                        "status": BindingStatus.ACTIVE,
                        "config": {
                            **probe_result.binding.config,
                            "probation": True,
                            "item_quota": self.probation_item_quota,
                        },
                    }
                )
                binding = binding.model_copy(update={"config_hash": canonical_hash(binding.config)})
                self.sources.add_binding(binding, reason="source_discovery_validated")
                accepted_count += 1
                reason = "validated_probation"
                target_id = saved.target_id
            decision = SourceCandidateDecision(
                decision_id=f"{self.id_factory('candidate-decision')}-{len(decisions) + 1}",
                discovery_run_id=run_id,
                candidate=candidate,
                accepted=accepted,
                target_id=target_id,
                reason=reason or "rejected",
                probe=probe_result,
            )
            decisions.append(decision)

        snapshot = self.sources.create_snapshot(snapshot_id=self.id_factory("source-snapshot"))
        rejected = sum(not decision.accepted for decision in decisions)
        status: Literal["succeeded", "succeeded_partial"] = (
            "succeeded_partial"
            if provider_errors or (accepted_count and rejected)
            else "succeeded"
        )
        run = SourceDiscoveryRun(
            discovery_run_id=run_id,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
            status=status,
            profile_hash=profile.profile_hash,
            due_reasons=due.reasons,
            started_at=started_at,
            finished_at=self.clock(),
            provider=self.provider.name,
            queries=queries,
            search_responses=retained_search_responses(responses),
            candidate_decision_ids=tuple(item.decision_id for item in decisions),
            previous_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot else None,
            output_snapshot_id=snapshot.snapshot_id,
            degraded_reasons=tuple(provider_errors),
            model_id=self.agent.model_id,
            prompt_version=self.agent.prompt_version,
            policy_version=self.policy_version,
            agent_audit={
                "node": "source_discovery",
                "model_id": self.agent.model_id,
                "prompt_version": self.agent.prompt_version,
                **getattr(
                    self.agent,
                    "last_audit",
                    {
                        "status": "ok",
                        "replayed": recorded_output is not None,
                        "usage": {},
                        "retry_limit": None,
                        "trace_event_kinds": [],
                    },
                ),
            },
        )
        self.discovery.append_run(run, tuple(decisions))
        return SourceDiscoveryResult(run=run, decisions=tuple(decisions), snapshot=snapshot)

    def observe_and_transition(self, observation: SourceObservation) -> SourceLifecycleDecision:
        self.discovery.append_observation(observation)
        target = self.sources.get_target(observation.target_id)
        if target is None:
            raise ValueError("source target not found")
        decision = decide_source_lifecycle(
            target.status, self.discovery.list_observations(target.target_id)
        )
        if decision.next_status != target.status:
            self.sources.set_target_status(
                target.target_id, decision.next_status, reason=decision.reason
            )
        return decision
