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

- The Web app entrypoint is `src/web_app.rb`.
- The browser shell is served from `src/web/public/`.
- Runtime signal data comes from `data/signals/latest.json`.
- The Web app can edit `config/user-profile.yml` and `config/sources.yml`.
- The implemented fetch path remains RSS-only.
- MCP/API/HTML/file source templates are not runnable fetchers in the current MVP.
