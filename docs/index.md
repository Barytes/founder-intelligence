# Documentation Index

Start here for current repository truth.

## Current implementation

- [Current Runtime Architecture](current-demo-architecture.md): the default L4 profile-driven workflow and its rollback path.
- [Web App Architecture](web-app/architecture.md): FastAPI routes, current three-column dashboard, Inbox, Inspector and same-origin policy.
- [Agent Core](agent-core/index.md): the PydanticAI runtime boundary and bounded Agent nodes.
- [Fetcher Adapters](fetcher-adapters.md): SourceTarget/AcquisitionBinding and current connector capabilities.
- [Ingestion](ingestion.md): canonical ingestion from connectors and Inbox.
- [Signal Processing](signal-processing.md): deterministic baseline, candidate pool, evidence-backed Agent assessment and code-owned final score.
- [Storage](storage.md): SQLite stores, immutable snapshots/traces and JSONL handoff artifacts.
- [L3/L4/L5 Roadmap](agent-roadmap/l3-l4-l5-roadmap.md): L4 is implemented; L5 remains future work.

## Current boundaries

- L4 is the default path. `FI_L4_LEGACY_FALLBACK=1` restores the old YAML/deterministic path for one release.
- `ProfileStore` is sourced from explicit `UserContextEvent` records. `config/user-profile.yml` is legacy compatibility only and is never imported as a real user.
- SQLite `SourceCatalog` is the source of truth. `config/sources.yml` is a backed-up bootstrap/import artifact, not a bidirectional runtime registry.
- SourceTarget identity is transport-independent. Implemented connectors are RSS, RSSHub and Inbox; arbitrary API/HTML/MCP/browser acquisition is not yet implemented.
- Source discovery uses a provider-neutral SearchProvider and local validation. A candidate never becomes active directly from Agent output.
- Agentic Core uses PydanticAI as its only model runtime. Workflow, repositories, connectors, validators and score policy remain framework-independent.
- The dashboard keeps the existing three-column news presentation and exposes current-info input, Inbox share, tracking state, score provenance and degraded state.

## Specifications and evidence

Implementation plans, milestone decisions, evaluation matrices and pressure tests live under `codex-workspace/docs/superpowers/` as required by the repository workspace policy.

Historical plans that describe Ruby refresh, YAML as current source of truth, RSS as the product identity, or L4 as a terminal briefing should not be used as current implementation documentation.
