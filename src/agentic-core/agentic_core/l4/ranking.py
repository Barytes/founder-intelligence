from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentic_core.l4.domain import (
    AgentAssessment,
    AgentNodeAudit,
    RankedSignal,
    ScoreProvenance,
)
from agentic_core.l4.repositories import AssessmentRepository
from agentic_core.pipeline import build_signals as deterministic_scorer


class RankingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidatePoolPolicy(RankingContract):
    version: Literal[1] = 1
    max_candidates: int = Field(default=20, ge=1, le=100)
    baseline_top: int = Field(default=10, ge=1, le=100)
    source_diverse: int = Field(default=3, ge=0, le=20)
    exploration: int = Field(default=3, ge=0, le=20)


class RankingCandidate(RankingContract):
    item: dict[str, Any]
    baseline: dict[str, Any]
    candidate_reasons: tuple[str, ...]


def _dedupe_key(item: dict[str, Any]) -> str:
    return str(
        item.get("normalized_link")
        or item.get("link")
        or item.get("content_hash")
        or item.get("id")
    )


def build_candidate_pool(
    items: Sequence[dict[str, Any]],
    baseline_assessments: Sequence[dict[str, Any]],
    *,
    policy: CandidatePoolPolicy = CandidatePoolPolicy(),
    pinned_source_ids: frozenset[str] = frozenset(),
) -> tuple[RankingCandidate, ...]:
    item_by_id = {str(item["id"]): item for item in items}
    baseline = sorted(
        baseline_assessments,
        key=lambda signal: (
            -float(signal["total_score"]),
            -float(signal["importance_score"]),
            -float(signal["relevance_score"]),
            str(signal.get("title")),
        ),
    )
    reasons: dict[str, list[str]] = {}

    def add(item_id: str, reason: str) -> None:
        if item_id not in item_by_id:
            return
        values = reasons.setdefault(item_id, [])
        if reason not in values:
            values.append(reason)

    for signal in baseline[: policy.baseline_top]:
        add(str(signal["id"]), "baseline_top")

    seen_sources: set[str] = set()
    for signal in baseline:
        item = item_by_id[str(signal["id"])]
        source_id = str(item.get("source_id") or "")
        if source_id and source_id not in seen_sources:
            add(str(signal["id"]), "source_diverse_sample")
            seen_sources.add(source_id)
        if len(seen_sources) >= policy.source_diverse:
            break

    top_tags = {
        str(tag)
        for signal in baseline[: policy.baseline_top]
        for tag in signal.get("tags", [])
    }
    for signal in baseline[policy.baseline_top :]:
        item = item_by_id[str(signal["id"])]
        if any(str(tag) not in top_tags for tag in item.get("tags", [])):
            add(str(signal["id"]), "new_topic_or_entity")
        if item.get("source_id") in pinned_source_ids or item.get("pinned") is True:
            add(str(signal["id"]), "pinned_source")
        if item.get("origin") == "user_shared":
            add(str(signal["id"]), "recent_shared_source_update")

    remaining = [
        signal
        for signal in baseline
        if str(signal["id"]) not in reasons
    ]
    # Stable hash ordering gives bounded exploration without runtime randomness.
    remaining.sort(key=lambda signal: str(signal["id"]))
    for signal in remaining[: policy.exploration]:
        add(str(signal["id"]), "bounded_exploration")

    selected: list[RankingCandidate] = []
    seen_keys: set[str] = set()
    baseline_by_id = {str(signal["id"]): signal for signal in baseline}
    for signal in baseline:
        item_id = str(signal["id"])
        if item_id not in reasons:
            continue
        key = _dedupe_key(item_by_id[item_id])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append(
            RankingCandidate(
                item=item_by_id[item_id],
                baseline=baseline_by_id[item_id],
                candidate_reasons=tuple(reasons[item_id]),
            )
        )
        if len(selected) >= policy.max_candidates:
            break
    return tuple(selected)


class HybridRankingPolicy(RankingContract):
    version: str = "hybrid-ranking-v1"
    baseline_weight: float = Field(default=0.65, ge=0, le=1)
    agent_weight: float = Field(default=0.35, ge=0, le=1)
    relevance_weight: float = Field(default=0.35, ge=0, le=1)
    novelty_weight: float = Field(default=0.2, ge=0, le=1)
    credibility_weight: float = Field(default=0.2, ge=0, le=1)
    urgency_weight: float = Field(default=0.15, ge=0, le=1)
    counter_signal_penalty: float = Field(default=0.1, ge=0, le=1)

    def model_post_init(self, _context: Any) -> None:
        if abs(self.baseline_weight + self.agent_weight - 1) > 1e-9:
            raise ValueError("baseline and agent weights must sum to one")
        dimension_total = (
            self.relevance_weight
            + self.novelty_weight
            + self.credibility_weight
            + self.urgency_weight
            + self.counter_signal_penalty
        )
        if abs(dimension_total - 1) > 1e-9:
            raise ValueError("agent dimension weights must sum to one")


def agent_component(
    assessment: AgentAssessment, policy: HybridRankingPolicy
) -> float:
    positive = (
        assessment.relevance * policy.relevance_weight
        + assessment.novelty * policy.novelty_weight
        + assessment.credibility * policy.credibility_weight
        + assessment.urgency * policy.urgency_weight
    )
    adjusted = max(0.0, positive - assessment.counter_signal * policy.counter_signal_penalty)
    return round(adjusted * 5, 4)


def compose_final_score(
    baseline: dict[str, Any],
    assessment: AgentAssessment | None,
    *,
    policy: HybridRankingPolicy = HybridRankingPolicy(),
    fallback_reason: str | None = None,
) -> ScoreProvenance:
    baseline_score = float(baseline["total_score"])
    components = {
        "importance": float(baseline["importance_score"]),
        "relevance": float(baseline["relevance_score"]),
    }
    if assessment is None:
        return ScoreProvenance(
            baseline_components=components,
            baseline_score=baseline_score,
            final_score=baseline_score,
            policy_version=policy.version,
            fallback_reason=fallback_reason or "not_assessed",
        )
    component = agent_component(assessment, policy)
    final = round(
        baseline_score * policy.baseline_weight + component * policy.agent_weight,
        4,
    )
    return ScoreProvenance(
        baseline_components=components,
        baseline_score=baseline_score,
        agent_component=component,
        final_score=final,
        policy_version=policy.version,
        assessment_id=assessment.assessment_id,
    )


class NewsAssessmentAgent(Protocol):
    model_id: str
    prompt_version: str

    def assess(
        self,
        *,
        item: dict[str, Any],
        profile_id: str | None,
        profile_fields: dict[str, Any],
        recorded_output: dict[str, Any] | BaseModel | None = None,
    ) -> AgentAssessment: ...


class ItemAssessmentResult(RankingContract):
    item_id: str
    status: Literal["assessed", "fallback"]
    assessment: AgentAssessment | None = None
    error: str | None = None


class HybridRankingResult(RankingContract):
    output: dict[str, Any]
    candidate_pool: tuple[RankingCandidate, ...]
    item_results: tuple[ItemAssessmentResult, ...]


def assessments_are_suspicious(assessments: Sequence[AgentAssessment]) -> bool:
    if len(assessments) < 3:
        return False
    return all(
        item.relevance >= 0.95
        and item.novelty >= 0.95
        and item.credibility >= 0.95
        and item.urgency >= 0.95
        and item.counter_signal <= 0.05
        for item in assessments
    )


class HybridRankingService:
    def __init__(
        self,
        *,
        agent: NewsAssessmentAgent,
        repository: AssessmentRepository | None = None,
        candidate_policy: CandidatePoolPolicy = CandidatePoolPolicy(),
        ranking_policy: HybridRankingPolicy = HybridRankingPolicy(),
        id_factory=lambda prefix: f"{prefix}-{uuid4()}",
    ):
        self.agent = agent
        self.repository = repository
        self.candidate_policy = candidate_policy
        self.ranking_policy = ranking_policy
        self.id_factory = id_factory
        self.last_agent_audits: list[dict[str, Any]] = []

    def rank(
        self,
        *,
        canonical: dict[str, Any],
        profile: dict[str, Any],
        rules: dict[str, Any],
        generated_at: str,
        top_n: int,
        workflow_run_id: str,
        profile_id: str | None = None,
        source_snapshot_id: str | None = None,
        recorded_outputs: dict[str, Any] | None = None,
    ) -> HybridRankingResult:
        now = datetime.fromisoformat(generated_at)
        baseline = deterministic_scorer.build_signals(
            canonical, profile, rules, max(len(canonical["items"]), 1), now=now
        )
        pool = build_candidate_pool(
            canonical["items"], baseline, policy=self.candidate_policy
        )
        results: list[ItemAssessmentResult] = []
        self.last_agent_audits = []
        valid: list[AgentAssessment] = []
        by_item: dict[str, AgentAssessment] = {}
        for candidate in pool:
            item_id = str(candidate.item["id"])
            try:
                assessment = self.agent.assess(
                    item=candidate.item,
                    profile_id=profile_id,
                    profile_fields=profile,
                    recorded_output=(recorded_outputs or {}).get(item_id),
                )
                self.last_agent_audits.append(
                    {
                        "item_id": item_id,
                        "node": "news_assessment",
                        "model_id": self.agent.model_id,
                        "prompt_version": self.agent.prompt_version,
                        **getattr(
                            self.agent,
                            "last_audit",
                            {
                                "status": "ok",
                                "replayed": recorded_outputs is not None,
                                "usage": {},
                                "retry_limit": None,
                                "trace_event_kinds": [],
                            },
                        ),
                    }
                )
                valid.append(assessment)
                by_item[item_id] = assessment
                results.append(
                    ItemAssessmentResult(
                        item_id=item_id, status="assessed", assessment=assessment
                    )
                )
            except Exception as exc:
                self.last_agent_audits.append(
                    {
                        "item_id": item_id,
                        "node": "news_assessment",
                        "model_id": self.agent.model_id,
                        "prompt_version": self.agent.prompt_version,
                        **getattr(self.agent, "last_audit", {}),
                        "status": "error",
                        "error_types": [exc.__class__.__name__],
                    }
                )
                results.append(
                    ItemAssessmentResult(
                        item_id=item_id,
                        status="fallback",
                        error=f"assessment failed ({exc.__class__.__name__})",
                    )
                )

        if assessments_are_suspicious(valid):
            by_item.clear()
            results = [
                ItemAssessmentResult(
                    item_id=result.item_id,
                    status="fallback",
                    error="assessment distribution rejected by calibration policy",
                )
                for result in results
            ]
            self.last_agent_audits = [
                {
                    **audit,
                    "status": "rejected_calibration",
                    "error_types": [
                        *(audit.get("error_types") or []),
                        "CalibrationRejected",
                    ],
                }
                for audit in self.last_agent_audits
            ]
        elif self.repository:
            # Persist only assessments that passed both item validation and the
            # run-level calibration gate. Rejected reward-hack distributions
            # must never appear as ASSESSED records in the audit store.
            for assessment in valid:
                self.repository.append_assessment(assessment)

        self.last_agent_audits = [
            AgentNodeAudit.model_validate(audit).model_dump(mode="json")
            for audit in self.last_agent_audits
        ]

        reasons_by_item = {
            str(candidate.item["id"]): candidate.candidate_reasons for candidate in pool
        }
        baseline_rank_by_item = {
            str(signal["id"]): rank for rank, signal in enumerate(baseline, start=1)
        }
        status_by_item = {result.item_id: result for result in results}
        deduped: dict[str, dict[str, Any]] = {}
        for signal in baseline:
            item = next(item for item in canonical["items"] if item["id"] == signal["id"])
            key = _dedupe_key(item)
            assessment = by_item.get(str(signal["id"]))
            item_status = status_by_item.get(str(signal["id"]))
            provenance = compose_final_score(
                signal,
                assessment,
                policy=self.ranking_policy,
                fallback_reason=item_status.error if item_status else "outside_candidate_pool",
            )
            enriched = dict(signal)
            enriched["total_score"] = provenance.final_score
            enriched["score_provenance"] = provenance.model_dump(mode="json")
            enriched["candidate_reasons"] = list(reasons_by_item.get(str(signal["id"]), ()))
            enriched["agent_status"] = "valid" if assessment else "fallback"
            enriched["agent_assessment"] = (
                assessment.model_dump(mode="json") if assessment else None
            )
            enriched["workflow_run_id"] = workflow_run_id
            enriched["profile_id"] = profile_id
            enriched["source_snapshot_id"] = source_snapshot_id
            enriched["baseline_rank"] = baseline_rank_by_item[str(signal["id"])]
            previous = deduped.get(key)
            if previous is None or enriched["total_score"] > previous["total_score"]:
                deduped[key] = enriched

        ranked = sorted(
            deduped.values(),
            key=lambda signal: (
                -float(signal["total_score"]),
                -float(signal["importance_score"]),
                -float(signal["relevance_score"]),
                str(signal.get("title")),
            ),
        )[:top_n]
        for final_rank, signal in enumerate(ranked, start=1):
            signal["final_rank"] = final_rank
            signal["rank_delta"] = int(signal["baseline_rank"]) - final_rank
        if self.repository:
            for rank, signal in enumerate(ranked, start=1):
                self.repository.append_ranked_signal(
                    RankedSignal(
                        signal_id=self.id_factory("ranked-signal"),
                        item_id=str(signal["id"]),
                        rank=rank,
                        score=ScoreProvenance.model_validate(signal["score_provenance"]),
                        candidate_reasons=tuple(signal["candidate_reasons"]),
                        profile_id=profile_id,
                        source_snapshot_id=source_snapshot_id,
                        workflow_run_id=workflow_run_id,
                        payload=signal,
                    )
                )
        output = {
            "contract_version": 1,
            "generated_at": generated_at,
            "input_run_id": canonical.get("run_id"),
            "workflow_run_id": workflow_run_id,
            "profile_id": profile_id,
            "profile_version": profile.get("version"),
            "source_snapshot_id": source_snapshot_id,
            "rules_version": rules.get("version"),
            "score_policy_version": self.ranking_policy.version,
            "agent_model_id": self.agent.model_id,
            "agent_prompt_version": self.agent.prompt_version,
            "summary": {
                "input_items": len(canonical["items"]),
                "signals": len(ranked),
                "top_n": top_n,
                "assessed": sum(item.status == "assessed" for item in results),
                "fallback": sum(item.status == "fallback" for item in results),
            },
            "signals": ranked,
        }
        return HybridRankingResult(
            output=output, candidate_pool=pool, item_results=tuple(results)
        )
