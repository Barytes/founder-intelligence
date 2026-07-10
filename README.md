# Founder Intelligence

Local MVP for a personal intelligence aggregator. One local FastAPI service
serves the signal console, Agentic Core workbench, and settings page.

## Start the Unified Web Service

Requirements:

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose are needed when running an RSS refresh

```bash
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

Then open:

| Page | Address | Purpose |
| --- | --- | --- |
| Signal console | `http://127.0.0.1:4567/` | View latest signals, edit the profile and RSS sources, and trigger a refresh. |
| Agent workbench | `http://127.0.0.1:4567/agent` | Use the local Agentic Core against existing project artifacts. |
| Settings | `http://127.0.0.1:4567/settings` | Configure local LLM providers and the GitHub token. |

The service is local-only when started with the command above. On startup it
attempts to start RSSHub with `docker compose -f config/docker-compose.yml up -d rsshub`.
Set `FI_AUTO_START_RSSHUB=0` to skip that attempt. The service can still start
without Docker, but a refresh will report its pipeline failure normally.

## Configure the Agent Workbench

The dashboard works without an LLM. To use the Agent workbench, create a local
environment file and configure a provider from `/settings`:

```bash
cp .env.example .env
```

The settings page writes provider API keys and `GITHUB_ACCESS_TOKEN` to `.env`.
It writes provider model/base URL choices to gitignored `config/agentic-core.local.yml`.
`config/agentic-core.example.yml` remains the committed default template.

The workbench reads existing pipeline artifacts such as `data/signals/latest.json`
and writes agentic outputs under `data/agentic/`.

## Refresh and Data Flow

The implemented refresh path is RSS-only:

1. Fetch source-native RSS items.
2. Normalize them into canonical items.
3. Store canonical items as JSONL.
4. Build user-matched intelligence signals and a daily dashboard.

Use the refresh action in the signal console for normal operation. The FastAPI
service runs this fixed Python pipeline internally; it does not enable the MCP,
API, HTML, or file source templates.

The latest successful signal payload is `data/signals/latest.json`. The Python
builder also produces `data/dashboard/latest.md` and
`data/dashboard/generated-latest.html`; these are generated reference artifacts,
not the Web app homepage.

For pipeline-only diagnosis, the equivalent commands are:

```bash
docker compose -f config/docker-compose.yml up -d rsshub
PYTHONPATH=src/agentic-core uv run python -m agentic_core.pipeline.runner --root .
```

## MVP Scope

This version includes the RSS-first aggregator, profile-based signal matching,
the local Web console, and a bounded local Agentic Core workbench. It does not
include a full ontology, a production multi-user chat product, accounts,
long-term memory, automatic action execution, or runnable non-RSS fetchers.

## Documentation

Start with `docs/index.md`.
