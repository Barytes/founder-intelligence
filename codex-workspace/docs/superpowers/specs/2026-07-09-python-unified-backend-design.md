# Python Unified Backend Design

## Requirement

Move the local HTTP backend to Python/FastAPI while keeping the existing Ruby pipeline scripts as the temporary business pipeline executor.

The unified backend must:

- Serve the current dashboard web app from `/`.
- Serve the Agentic Core workbench from `/agent`.
- Let the two pages jump to each other through a shared navigation element.
- Preserve the dashboard's existing visual style.
- Bring the agent workbench closer to the dashboard's visual language.
- Keep the implemented fetch path RSS-only.
- Keep `config/` stable except for the existing browser-editable files and the Agentic Core local config/secret files already used by the workbench.
- Keep Ruby scripts as command-line pipeline steps for refresh until they are deliberately replaced later.

## Architecture

FastAPI becomes the only HTTP service. The previous Ruby Web app is treated as the behavior reference for migration and removed from the current runtime.

```text
Browser
  |
  v
uvicorn web_workbench.app:app
  |
  +-- / dashboard static shell from src/web/public
  +-- /agent agent workbench static shell from src/agentic-core/web_workbench/static
  +-- /api/* dashboard data/config/refresh APIs
  +-- /api/agent/* Agentic Core APIs
  |
  +-- Python dashboard repository
  +-- Python pipeline runner -> ruby src/*.rb scripts
  +-- Python Agentic Core
```

The Ruby pipeline scripts remain authoritative for fetch, ingest, store, and signal build:

```text
ruby src/fetch_rss.rb
ruby src/ingest_adapter_output.rb
ruby src/store_canonical_jsonl.rb
ruby src/build_signals.rb
```

The Python runner owns the HTTP-facing refresh lifecycle: lock file, refresh status, subprocess execution, artifact validation, safe publish, and stale-success preservation.

## Route Contract

Dashboard routes:

- `GET /`
- `GET /app.js`
- `GET /styles.css`
- `GET /assets/...`
- `GET /api/signals/latest`
- `GET /api/runs/latest`
- `GET /api/refresh/status`
- `GET /api/profile`
- `PUT /api/profile`
- `GET /api/sources`
- `PUT /api/sources`
- `POST /api/sources/{source_id}`
- `PATCH /api/sources/{source_id}`
- `GET /api/health`
- `POST /api/refresh`

Agent routes:

- `GET /agent`
- `GET /agent/static/...`
- `GET /api/agent/default-config`
- `POST /api/agent/provider-settings`
- `POST /api/agent/chat`

The existing non-prefixed agent API routes may remain as compatibility aliases during the migration, but the workbench UI should call the `/api/agent/*` routes.

## Evaluation Plan

Automated checks must prove:

- FastAPI serves both dashboard and agent pages from one app.
- Dashboard HTML contains navigation to `/agent`.
- Agent HTML contains navigation back to `/`.
- Dashboard APIs preserve the Ruby Web app behavior for latest signals, sources, profile, source toggles, and same-origin refresh protection.
- Refresh rejects command/script/path/argv/args parameters.
- Refresh delegates to a Python runner that invokes Ruby-compatible command argv.
- A successful refresh publishes validated signals and writes status.
- A failed refresh preserves the previous `data/signals/latest.json`.
- Agent provider and chat APIs still pass their existing tests.

Manual smoke should verify:

- `uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567` opens the dashboard at `/`.
- `/agent` opens the Agentic Core workbench.
- Navigation works both directions.

## Pressure Test

Known risks:

- Migrating the HTTP layer could accidentally change dashboard API semantics. Mitigation: port the existing Ruby tests into FastAPI tests before implementation.
- A Python runner can drift from the Ruby runner. Mitigation: keep the same status schema and artifact validation behavior.
- Keeping old Ruby Web app code would confuse future agents. Mitigation: remove the old Ruby HTTP backend and keep only the Ruby pipeline scripts.
- `uv run pytest` does not install the dev extra by default in a fresh worktree. Mitigation: use `uv run --extra dev pytest`.
