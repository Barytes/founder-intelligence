# Documentation Index

Start here when working on this repository.

## Primary Documents

- [Current Runtime Architecture](current-demo-architecture.md): explains the current RSS-only pipeline, Web app wrapper, runtime boundaries, and workflow.
- [Current Web App Architecture](web-app/architecture.md): explains the implemented FastAPI local Web app architecture, routes, frontend data flow, refresh runner, and runtime boundaries.
- [YAML Deterministic Pipeline](yaml-deterministic-pipeline.md): explains how YAML configuration drives the deterministic pipeline, what each YAML file does, and how each one participates in code flow.
- [Agent Core](agent-core/index.md): explains the implemented Agentic Core architecture, runtime flow, configuration model, workbench, and known risks.

## Feature Documents

- [Web App Feature Docs](web-app/README.md): collects current architecture, issue, and verification documents for the implemented Web app.
- [Current Web App Known Issues](web-app/current-demo-issues.md): records resolved issues, remaining limitations, and repair priorities.
- [Web App Verification Guide](web-app/test-plan.md): defines automated checks, HTTP smoke, and real browser smoke for the current Web app.

## Supporting Documents

- [Fetcher Adapters](fetcher-adapters.md): describes the fetcher/ingestion boundary and the RSS-first adapter design.
- [Ingestion](ingestion.md): describes canonical item normalization and ingestion responsibilities.
- [Signal Processing](signal-processing.md): describes deterministic signal matching, scoring, and dashboard generation.
- [Storage](storage.md): describes local append-only JSONL storage.

## Important Runtime Boundaries

- Current implemented fetch path is RSS-only.
- The current HTTP backend is Python/FastAPI; refresh still delegates to Ruby pipeline scripts.
- MCP/API/HTML source templates and contracts exist, but no runnable fetcher is implemented for them yet.
- Schedule fields exist in configuration, but no scheduler consumes them yet.
- `config/sources.yml` is the only source registry used by the main demo flow.
- The Web app can edit `config/user-profile.yml` and `config/sources.yml`; other `config/` files remain manual.

## Archive

- [Archived Web App Refactor Plan](archive/web-app/refactor-plan.md): historical implementation plan for the Web app upgrade.
- [Archived Architecture Pressure Test](archive/web-app/pressure-test.md): historical pressure-test notes for the refactor plan.
- [Archived Test Plan Pressure Test](archive/web-app/test-plan-pressure-test.md): historical audit of the old test plan.
