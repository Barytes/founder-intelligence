from __future__ import annotations

from typing import Any

from agentic_core.l4.hashing import canonical_hash
from agentic_core.l4.repositories import (
    AssessmentRepository,
    ContextEventRepository,
    ProfileRepository,
    RuntimeControlRepository,
    SourceDiscoveryRepository,
    SourceRepository,
    WorkflowRepository,
)


class WorkflowInspector:
    def __init__(self, database: Any):
        self.workflows = WorkflowRepository(database)
        self.events = ContextEventRepository(database)
        self.profiles = ProfileRepository(database)
        self.sources = SourceRepository(database)
        self.discovery = SourceDiscoveryRepository(database)
        self.assessments = AssessmentRepository(database)
        self.controls = RuntimeControlRepository(database)

    def list_runs(self, limit: int = 100) -> dict[str, Any]:
        runs = self.workflows.list_runs(limit=limit)
        return {
            "status": "ok",
            "runs": [run.model_dump(mode="json") for run in runs],
            "runtime_controls": self.controls.get_all(),
        }

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        run = self.workflows.get_run(run_id)
        if run is None:
            return None
        traces = self.workflows.list_traces(run_id)
        profile = self.profiles.get(run.profile_id) if run.profile_id else None
        profile_events = (
            [
                event
                for event_id in profile.based_on_event_ids
                if (event := self.events.get(event_id)) is not None
            ]
            if profile
            else []
        )
        source_snapshot = (
            self.sources.get_snapshot(run.source_snapshot_id)
            if run.source_snapshot_id
            else None
        )
        discovery_runs = [
            item
            for item in self.discovery.list_runs()
            if item.workflow_run_id == run_id
            or (
                item.workflow_run_id is None
                and (
                    item.output_snapshot_id == run.source_snapshot_id
                    or item.previous_snapshot_id == run.source_snapshot_id
                )
            )
        ]
        decisions = [
            decision
            for discovery_run in discovery_runs
            for decision in self.discovery.list_decisions(discovery_run.discovery_run_id)
        ]
        ranked = self.assessments.list_ranked_signals(run_id)
        assessments = [
            assessment
            for item_id in dict.fromkeys(signal.item_id for signal in ranked)
            for assessment in self.assessments.list_assessments(item_id)
            if assessment.assessment_id
            in {signal.score.assessment_id for signal in ranked if signal.score.assessment_id}
        ]
        observations = [
            observation
            for resolved in (source_snapshot.sources if source_snapshot else ())
            for observation in self.discovery.list_observations(resolved.target.target_id)
        ]
        return {
            "status": "ok",
            "run": run.model_dump(mode="json"),
            "timeline": [trace.model_dump(mode="json") for trace in traces],
            "profile": profile.model_dump(mode="json") if profile else None,
            "profile_events": [event.model_dump(mode="json") for event in profile_events],
            "source_snapshot": (
                source_snapshot.model_dump(mode="json") if source_snapshot else None
            ),
            "source_discovery_runs": [
                item.model_dump(mode="json") for item in discovery_runs
            ],
            "source_candidate_decisions": [
                item.model_dump(mode="json") for item in decisions
            ],
            "source_observations": [
                item.model_dump(mode="json") for item in observations
            ],
            "assessments": [item.model_dump(mode="json") for item in assessments],
            "ranked_signals": [item.model_dump(mode="json") for item in ranked],
            "runtime_controls": self.controls.get_all(),
            "chain_of_thought": None,
        }

    def replay(self, run_id: str) -> dict[str, Any] | None:
        run = self.workflows.get_run(run_id)
        if run is None:
            return None
        ranked = self.assessments.list_ranked_signals(run_id)
        if not ranked:
            ordering_hash = run.usage.get("published_ordering_hash")
            if ordering_hash:
                return {
                    "status": "replayed",
                    "run_id": run_id,
                    "external_calls": 0,
                    "ordering": [],
                    "ordering_hash": ordering_hash,
                    "signals": [],
                }
            return {
                "status": "not_replayable",
                "run_id": run_id,
                "external_calls": 0,
                "reason": "no persisted final ordering",
                "ordering": [],
                "signals": [],
            }
        ordered = sorted(ranked, key=lambda item: item.rank)
        return {
            "status": "replayed",
            "run_id": run_id,
            "external_calls": 0,
            "ordering": [item.item_id for item in ordered],
            "ordering_hash": canonical_hash(
                [(item.rank, item.item_id, item.score.final_score) for item in ordered]
            ),
            "signals": [item.payload for item in ordered],
        }

    def rollback_profile(self, user_id: str, profile_id: str) -> dict[str, Any]:
        snapshot = self.profiles.rollback(user_id, profile_id)
        return {
            "status": "rolled_back",
            "profile": snapshot.model_dump(mode="json"),
        }

    def rollback_source_snapshot(
        self, scope_id: str, snapshot_id: str
    ) -> dict[str, Any]:
        snapshot = self.sources.rollback_snapshot(snapshot_id, scope_id=scope_id)
        return {
            "status": "rolled_back",
            "source_snapshot": snapshot.model_dump(mode="json"),
            "pinned": True,
        }
