# Python Unified Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: implemented on `codex/python-unified-backend`. This file is now an execution record as well as the original implementation plan.

**Goal:** Replace the local HTTP backend with one FastAPI app while keeping the existing Ruby scripts as the refresh pipeline executor.

**Architecture:** Extend `web_workbench.app` into the unified FastAPI service. Add Python dashboard repository and pipeline runner modules that preserve the current Ruby Web app API contract. Serve the dashboard at `/`, the agent workbench at `/agent`, the settings page at `/settings`, and prefix Agentic Core APIs under `/api/agent/*`.

**Tech Stack:** Python 3.11, FastAPI, pytest, PyYAML, uvicorn, existing Ruby scripts.

---

## Files

- Modify `src/agentic-core/web_workbench/app.py`: expose unified routes and app factory.
- Create `src/agentic-core/web_workbench/dashboard_repository.py`: Python data/config layer for dashboard APIs.
- Create `src/agentic-core/web_workbench/pipeline_runner.py`: Python refresh runner that calls Ruby scripts.
- Modify `src/web/public/index.html`: add navigation to Agent Workbench.
- Modify `src/web/public/styles.css`: add shared nav styling.
- Modify `src/agentic-core/web_workbench/static/index.html`: add navigation back to dashboard/settings and use `/agent/static/*`.
- Modify `src/agentic-core/web_workbench/static/app.js`: call `/api/agent/*` APIs.
- Add `src/agentic-core/web_workbench/static/settings.html`: local provider/GitHub token settings page.
- Add `src/agentic-core/web_workbench/static/settings.js`: settings page behavior.
- Modify `src/agentic-core/web_workbench/static/styles.css`: align workbench styling with the dashboard.
- Add `tests/test_unified_web_app.py`: FastAPI tests for dashboard routes and API behavior.
- Add `tests/test_python_pipeline_runner.py`: Python refresh runner behavior tests.
- Update `docs/index.md`, `docs/web-app/architecture.md`, `docs/agent-core/index.md`, and `README.md`.

## Tasks

- [x] Write failing FastAPI tests for dashboard page/static/API routes.
- [x] Implement `DashboardRepository` until those tests pass.
- [x] Write failing tests for refresh runner success/failure/lock behavior.
- [x] Implement `PipelineRunner` until those tests pass.
- [x] Add unified routes and same-origin checks to `web_workbench.app`.
- [x] Move Agent Workbench UI calls to `/api/agent/*`.
- [x] Add cross-navigation and style alignment.
- [x] Add `/settings` and settings APIs for local provider/GitHub token configuration.
- [x] Update docs to make FastAPI the current HTTP entrypoint and Ruby scripts the retained pipeline executor.
- [x] Remove the old Ruby HTTP backend files and Ruby Web app tests after the Python behavior is covered.
- [x] Run `uv run --extra dev pytest`.
- [x] Start the FastAPI server and smoke `GET /`, `GET /agent`, `GET /settings`, `GET /api/health`, and `GET /api/agent/default-config`.
