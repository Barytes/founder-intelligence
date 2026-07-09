# Documentation Index

Start here when working on this repository.

## Primary Documents

- [Current Runtime Architecture](current-demo-architecture.md): explains the current RSS-only pipeline, Web app wrapper, runtime boundaries, and workflow.
- [Current Web App Architecture](web-app/architecture.md): explains the implemented FastAPI local Web app architecture, routes, frontend data flow, refresh runner, and runtime boundaries.
- [YAML Deterministic Pipeline](yaml-deterministic-pipeline.md): explains how YAML configuration drives the deterministic pipeline, what each YAML file does, and how each one participates in code flow.
- [Agent Core](agent-core/index.md): explains the implemented Agentic Core architecture, runtime flow, configuration model, workbench, and known risks.
- [L3-L4-L5 Agentic Roadmap](agent-roadmap/l3-l4-l5-roadmap.md): explains the staged path from tool contracts to fixed agent workflow to agentic controller.
- [L3 Tool Contract Architecture](agent-roadmap/l3-tool-contract-architecture.md): defines the L3 tool boundary, contracts, permissions, and L4/L5 extension path.
- [L3 Tool Contract Implementation Plan](agent-roadmap/l3-tool-contract-implementation-plan.md): provides the executable implementation plan for controlled L3 runtime tools.
- [L3 Tool Contract Evaluation Plan](agent-roadmap/l3-tool-contract-evaluation-plan.md): defines acceptance gates, reward-hack checks, and verification commands for L3.
- [L3 Tool Contract Pressure Test](agent-roadmap/l3-tool-contract-pressure-test.md): records plan vulnerabilities found and the design revisions that close them.
- [L3.5 Python Pipeline Migration Plan](agent-roadmap/l3-5-python-pipeline-migration-plan.md): explains how to replace the transitional Ruby wrapper with a Python-native pipeline while preserving L3 tool contracts.

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
- The Web app can edit `config/user-profile.yml` and `config/sources.yml`.
- The settings page can write local secrets to `.env` and provider overrides to gitignored `config/agentic-core.local.yml`.
- Other committed `config/` files remain manual unless a document or feature explicitly says otherwise.

## Archive

- [Archived Web App Refactor Plan](archive/web-app/refactor-plan.md): historical implementation plan for the Web app upgrade.
- [Archived Architecture Pressure Test](archive/web-app/pressure-test.md): historical pressure-test notes for the refactor plan.
- [Archived Test Plan Pressure Test](archive/web-app/test-plan-pressure-test.md): historical audit of the old test plan.
