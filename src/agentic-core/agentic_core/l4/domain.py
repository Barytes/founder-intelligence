from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextEventType(str, Enum):
    USER_STATEMENT = "user_statement"
    GOAL_UPDATE = "goal_update"
    SHARED_CONTENT = "shared_content"
    PROFILE_CORRECTION = "profile_correction"
    FOLLOW = "follow"
    UNFOLLOW = "unfollow"
    PASSIVE_BEHAVIOR = "passive_behavior"


class Explicitness(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class SourceKind(str, Enum):
    WEBSITE = "website"
    PUBLICATION = "publication"
    CREATOR = "creator"
    ORGANIZATION = "organization"
    REPOSITORY = "repository"
    FEED = "feed"
    INBOX = "inbox"
    TEMPLATE = "template"


class SourceStatus(str, Enum):
    CANDIDATE = "candidate"
    PROBATION = "probation"
    ACTIVE = "active"
    PAUSED = "paused"
    REJECTED = "rejected"
    UNHEALTHY = "unhealthy"
    RETIRED = "retired"
    INACTIVE = "inactive"


class ConnectorType(str, Enum):
    RSS = "rss"
    RSSHUB = "rsshub"
    INBOX = "inbox"
    API = "api"
    HTML = "html"
    BROWSER = "browser"
    MCP = "mcp"


class BindingStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    INVALID = "invalid"
    UNHEALTHY = "unhealthy"


class AssessmentStatus(str, Enum):
    ASSESSED = "assessed"
    FALLBACK = "fallback"
    REJECTED = "rejected"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SUCCEEDED_PARTIAL = "succeeded_partial"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"


class InboxStatus(str, Enum):
    SAVED = "saved"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    FAILED = "failed"


class AgentNodeAudit(ContractModel):
    """Framework-neutral, chain-of-thought-free audit projection for L4 nodes."""

    version: Literal[1] = 1
    node: Literal["profile_compiler", "source_discovery", "news_assessment"]
    status: str
    model_id: str | None = None
    prompt_version: str | None = None
    policy_version: str | None = None
    item_id: str | None = None
    replayed: bool = False
    retry_limit: int | None = Field(default=None, ge=0)
    usage: dict[str, Any] = Field(default_factory=dict)
    trace_event_kinds: tuple[str, ...] = ()
    error_types: tuple[str, ...] = ()


class UserContextEvent(ContractModel):
    version: Literal[1] = 1
    event_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    event_type: ContextEventType
    payload: dict[str, Any]
    origin: str = Field(min_length=1)
    explicitness: Explicitness
    confidence: float = Field(default=1.0, ge=0, le=1)
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=utc_now)
    supersedes_event_ids: tuple[str, ...] = ()
    idempotency_key: str = Field(min_length=1)


class ProfileField(ContractModel):
    version: Literal[1] = 1
    value: Any
    provenance_event_ids: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    inferred: bool = False
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def inferred_fields_expire(self) -> "ProfileField":
        if self.inferred and self.expires_at is None:
            raise ValueError("inferred profile fields require expires_at")
        if not self.provenance_event_ids:
            raise ValueError("profile fields require provenance")
        return self


class ProfileSnapshot(ContractModel):
    version: Literal[1] = 1
    profile_id: str
    user_id: str
    based_on_event_ids: tuple[str, ...]
    fields: dict[str, ProfileField]
    created_at: datetime = Field(default_factory=utc_now)
    model_id: str
    prompt_version: str
    policy_version: str
    validation_status: Literal["valid"] = "valid"
    profile_hash: str
    compile_audit: AgentNodeAudit | None = None


class EffectiveProfile(ContractModel):
    version: Literal[1] = 1
    user_id: str
    initialized: bool
    profile_id: str | None = None
    profile_hash: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    resolved_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def initialized_has_identity(self) -> "EffectiveProfile":
        if self.initialized and (not self.profile_id or not self.profile_hash):
            raise ValueError("initialized profile requires id and hash")
        if not self.initialized and (self.profile_id or self.profile_hash or self.fields):
            raise ValueError("uninitialized profile must be neutral")
        return self


class SourceTarget(ContractModel):
    version: Literal[1] = 1
    target_id: str
    source_kind: SourceKind
    provider: str
    canonical_external_id: str | None = None
    canonical_url: str | None = None
    display_name: str
    identity_key: str
    status: SourceStatus = SourceStatus.CANDIDATE
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def has_stable_identity(self) -> "SourceTarget":
        if not self.canonical_external_id and not self.canonical_url:
            raise ValueError("source target requires external id or canonical URL")
        return self


class AcquisitionBinding(ContractModel):
    version: Literal[1] = 1
    binding_id: str
    target_id: str
    connector_type: ConnectorType
    config: dict[str, Any]
    config_hash: str
    credential_refs: tuple[str, ...] = ()
    status: BindingStatus = BindingStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResolvedSource(ContractModel):
    version: Literal[1] = 1
    target: SourceTarget
    binding: AcquisitionBinding


class ResolvedSourceSnapshot(ContractModel):
    version: Literal[1] = 1
    snapshot_id: str
    sources: tuple[ResolvedSource, ...]
    snapshot_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    workflow_run_id: str | None = None


class EvidenceSpan(ContractModel):
    version: Literal[1] = 1
    field: Literal["title", "summary", "content"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str

    @model_validator(mode="after")
    def valid_range(self) -> "EvidenceSpan":
        if self.end <= self.start:
            raise ValueError("evidence span end must be after start")
        return self


class AgentAssessment(ContractModel):
    version: Literal[1] = 1
    assessment_id: str
    item_id: str
    profile_id: str | None = None
    relevance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    credibility: float = Field(ge=0, le=1)
    urgency: float = Field(ge=0, le=1)
    counter_signal: float = Field(ge=0, le=1)
    reasoning_summary: str
    evidence_spans: tuple[EvidenceSpan, ...]
    status: AssessmentStatus = AssessmentStatus.ASSESSED
    model_id: str
    prompt_version: str
    created_at: datetime = Field(default_factory=utc_now)


class ScoreProvenance(ContractModel):
    version: Literal[1] = 1
    baseline_components: dict[str, float]
    baseline_score: float
    agent_component: float | None = None
    final_score: float
    policy_version: str
    assessment_id: str | None = None
    fallback_reason: str | None = None


class RankedSignal(ContractModel):
    version: Literal[1] = 1
    signal_id: str
    item_id: str
    rank: int = Field(ge=1)
    score: ScoreProvenance
    candidate_reasons: tuple[str, ...]
    profile_id: str | None = None
    source_snapshot_id: str | None = None
    workflow_run_id: str
    payload: dict[str, Any]


class WorkflowRun(ContractModel):
    version: Literal[1] = 1
    run_id: str
    status: WorkflowStatus
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    profile_id: str | None = None
    source_snapshot_id: str | None = None
    input_hash: str
    output_hash: str | None = None
    degraded_reasons: tuple[str, ...] = ()
    usage: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepTrace(ContractModel):
    version: Literal[1] = 1
    trace_id: str
    run_id: str
    step_name: str
    sequence: int = Field(ge=1)
    status: StepStatus
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    input_hash: str
    output_hash: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    policy_version: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class InboxItem(ContractModel):
    version: Literal[1] = 1
    inbox_item_id: str
    user_id: str
    url: str
    title: str | None = None
    note: str | None = None
    captured_content: str | None = None
    status: InboxStatus = InboxStatus.SAVED
    source_target_id: str | None = None
    tracking_state: str = "unresolved"
    canonical_item: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)
