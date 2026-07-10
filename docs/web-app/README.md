# Web App Docs

This directory contains the current documentation for the implemented local Web app.

Start here:

- [Architecture](architecture.md): current Web app routes, frontend data flow, config APIs, refresh runner, and runtime boundaries.
- [Current Issues](current-demo-issues.md): resolved issues, remaining limitations, and repair priority.
- [Verification Guide](test-plan.md): automated tests, HTTP smoke, and real browser smoke checklist.

Historical planning documents were moved to:

- [Archive: Web App Refactor Plan](../archive/web-app/refactor-plan.md)
- [Archive: Architecture Pressure Test](../archive/web-app/pressure-test.md)
- [Archive: Test Plan Pressure Test](../archive/web-app/test-plan-pressure-test.md)

Current runtime facts:

- The Web app entrypoint is `web_workbench.app` via FastAPI/Uvicorn.
- The browser shell is served from `src/web/public/`.
- Agent Workbench and Settings are served from `src/agentic-core/web_workbench/static/`.
- Runtime signal data comes from `data/signals/latest.json`.
- The Web app can edit `config/user-profile.yml` and `config/sources.yml`.
- Settings can write local provider secrets/GitHub token to `.env` and provider overrides to gitignored `config/agentic-core.local.yml`.
- The implemented fetch path remains RSS-only.
- Browser refresh and Agent refresh both use the same Python-native RSS-only runner.
- MCP/API/HTML/file source templates are not runnable fetchers in the current MVP.
