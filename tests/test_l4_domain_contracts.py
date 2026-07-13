from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentic_core.l4.domain import (
    AcquisitionBinding,
    AgentAssessment,
    BindingStatus,
    ConnectorType,
    ContextEventType,
    EffectiveProfile,
    EvidenceSpan,
    Explicitness,
    ProfileField,
    ProfileSnapshot,
    RankedSignal,
    ResolvedSource,
    ResolvedSourceSnapshot,
    ScoreProvenance,
    SourceKind,
    SourceStatus,
    SourceTarget,
    StepStatus,
    UserContextEvent,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepTrace,
)
from agentic_core.l4.hashing import (
    canonical_hash,
    normalize_url,
    profile_snapshot_hash,
    source_identity_key,
)


NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def event() -> UserContextEvent:
    return UserContextEvent(
        event_id="event-1",
        user_id="user-1",
        event_type=ContextEventType.USER_STATEMENT,
        payload={"text": "I care about agent reliability"},
        origin="test",
        explicitness=Explicitness.EXPLICIT,
        occurred_at=NOW,
        recorded_at=NOW,
        idempotency_key="context:v1:event-1",
    )


def profile() -> ProfileSnapshot:
    draft = ProfileSnapshot(
        profile_id="profile-1",
        user_id="user-1",
        based_on_event_ids=("event-1",),
        fields={
            "interests": ProfileField(
                value=["agent reliability"],
                provenance_event_ids=("event-1",),
                confidence=1,
            )
        },
        created_at=NOW,
        model_id="fixture-model",
        prompt_version="profile-v1",
        policy_version="policy-v1",
        profile_hash="pending",
    )
    return draft.model_copy(
        update={
            "profile_hash": profile_snapshot_hash(draft)
        }
    )


def target() -> SourceTarget:
    identity = source_identity_key(
        source_kind=SourceKind.CREATOR,
        provider="bilibili",
        canonical_external_id="uid-42",
    )
    return SourceTarget(
        target_id="target-1",
        source_kind=SourceKind.CREATOR,
        provider="bilibili",
        canonical_external_id="uid-42",
        canonical_url="https://space.bilibili.com/42",
        display_name="Fixture Creator",
        identity_key=identity,
        status=SourceStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def binding() -> AcquisitionBinding:
    config = {"route": "/bilibili/user/video/42"}
    return AcquisitionBinding(
        binding_id="binding-1",
        target_id="target-1",
        connector_type=ConnectorType.RSSHUB,
        config=config,
        config_hash=canonical_hash(config),
        status=BindingStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    "model",
    [
        event(),
        profile(),
        EffectiveProfile(
            user_id="user-1",
            initialized=True,
            profile_id="profile-1",
            profile_hash="hash",
            fields={"interests": ["agents"]},
            resolved_at=NOW,
        ),
        target(),
        binding(),
        ResolvedSourceSnapshot(
            snapshot_id="snapshot-1",
            sources=(ResolvedSource(target=target(), binding=binding()),),
            snapshot_hash="snapshot-hash",
            created_at=NOW,
        ),
        AgentAssessment(
            assessment_id="assessment-1",
            item_id="item-1",
            relevance=0.9,
            novelty=0.8,
            credibility=0.7,
            urgency=0.6,
            counter_signal=0.1,
            reasoning_summary="Relevant to the explicit goal.",
            evidence_spans=(
                EvidenceSpan(field="summary", start=0, end=8, quote="Relevant"),
            ),
            model_id="fixture-model",
            prompt_version="assessment-v1",
            created_at=NOW,
        ),
        RankedSignal(
            signal_id="signal-1",
            item_id="item-1",
            rank=1,
            score=ScoreProvenance(
                baseline_components={"importance": 70},
                baseline_score=70,
                agent_component=80,
                final_score=75,
                policy_version="ranking-v1",
            ),
            candidate_reasons=("baseline_high",),
            workflow_run_id="run-1",
            payload={"title": "Fixture"},
        ),
        WorkflowRun(
            run_id="run-1",
            status=WorkflowStatus.RUNNING,
            started_at=NOW,
            input_hash="input-hash",
        ),
        WorkflowStepTrace(
            trace_id="trace-1",
            run_id="run-1",
            step_name="profile",
            sequence=1,
            status=StepStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
            input_hash="input-hash",
            output_hash="output-hash",
        ),
    ],
)
def test_domain_models_round_trip(model):
    restored = model.__class__.model_validate_json(model.model_dump_json())

    assert restored == model
    assert restored.version == 1


def test_all_domain_models_forbid_unknown_fields():
    payload = event().model_dump(mode="json")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="unexpected"):
        UserContextEvent.model_validate(payload)


def test_inferred_profile_field_requires_ttl_and_provenance():
    with pytest.raises(ValidationError, match="expires_at"):
        ProfileField(
            value="temporary",
            provenance_event_ids=("event-1",),
            confidence=0.5,
            inferred=True,
        )

    field = ProfileField(
        value="temporary",
        provenance_event_ids=("event-1",),
        confidence=0.5,
        inferred=True,
        expires_at=NOW + timedelta(days=1),
    )
    assert field.inferred is True


def test_neutral_effective_profile_cannot_smuggle_default_interests():
    with pytest.raises(ValidationError, match="neutral"):
        EffectiveProfile(
            user_id="user-1",
            initialized=False,
            fields={"interests": ["hard-coded"]},
        )


def test_source_identity_prefers_external_id_over_mutable_url():
    first = source_identity_key(
        source_kind="creator",
        provider="bilibili",
        canonical_external_id="42",
        canonical_url="https://space.bilibili.com/42",
    )
    moved = source_identity_key(
        source_kind="creator",
        provider="bilibili",
        canonical_external_id="42",
        canonical_url="https://www.bilibili.com/user/42",
    )

    assert first == moved


def test_url_identity_is_versioned_and_normalized():
    assert normalize_url("HTTPS://Example.COM:443/news/?b=2&a=1#fragment") == (
        "https://example.com/news?a=1&b=2"
    )
    assert source_identity_key(
        source_kind="website",
        provider="web",
        canonical_url="https://example.com/news/",
    ) == source_identity_key(
        source_kind="website",
        provider="WEB",
        canonical_url="https://EXAMPLE.com:443/news#x",
    )
