# Documentation Index

Start here when working on this repository.

## Primary Documents

- [Current Demo Architecture](current-demo-architecture.md): explains the current demo's functionality, architecture, runtime boundaries, and workflow.
- [YAML Deterministic Pipeline](yaml-deterministic-pipeline.md): explains how YAML configuration drives the deterministic pipeline, what each YAML file does, and how each one participates in code flow.
- [Agent Core](agent-core/index.md): explains the implemented Agentic Core architecture, runtime flow, configuration model, workbench, and known risks.

## Supporting Documents

- [Fetcher Adapters](fetcher-adapters.md): describes the fetcher/ingestion boundary and the RSS-first adapter design.
- [Ingestion](ingestion.md): describes canonical item normalization and ingestion responsibilities.
- [Signal Processing](signal-processing.md): describes deterministic signal matching, scoring, and dashboard generation.
- [Storage](storage.md): describes local append-only JSONL storage.

## Important Runtime Boundaries

- Current implemented fetch path is RSS-only.
- MCP/API/HTML source templates and contracts exist, but no runnable fetcher is implemented for them yet.
- Schedule fields exist in configuration, but no scheduler consumes them yet.
- `config/rss-sources.yml` is not used by the main demo flow.
