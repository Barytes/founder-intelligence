# Founder Intelligence

Local MVP for a personal intelligence aggregator.

The current pipeline is:

1. Fetch source-native RSS items.
2. Normalize them into canonical items.
3. Store canonical items as JSONL.
4. Build user-matched intelligence signals and a daily dashboard.

## Run

```bash
docker compose -f config/docker-compose.yml up -d rsshub
ruby src/fetch_rss.rb --output data/adapter-output/rss-fetch-latest.json
ruby src/ingest_adapter_output.rb --input data/adapter-output/rss-fetch-latest.json --output data/canonical-items/latest.json
ruby src/store_canonical_jsonl.rb --input data/canonical-items/latest.json --store-dir data/store
ruby src/build_signals.rb --input data/canonical-items/latest.json --profile config/user-profile.yml --rules config/signal-rules.yml
```

The generated signal artifacts are written to:

- `data/dashboard/latest.md`
- `data/dashboard/generated-latest.html`

`data/dashboard/generated-latest.html` is a transitional static HTML artifact from `src/build_signals.rb`.
The current Web app shell lives under `src/web/public/`.

## Run Web App

```bash
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

Then open:

```text
http://127.0.0.1:4567/
```

The Web app is local-only by default and reads the latest successful signals from `data/signals/latest.json`.
It can trigger a manual RSS-only refresh and edit `config/user-profile.yml` plus `config/sources.yml` from the browser.
It also serves `/agent` for the local Agentic Core workbench and `/settings` for local provider/GitHub token settings.
The HTTP backend is now the Python/FastAPI app; refresh still executes the existing Ruby pipeline scripts.
Startup runs `docker compose -f config/docker-compose.yml up -d rsshub` by default. Set `FI_AUTO_START_RSSHUB=0` to skip Docker startup. If Docker is unavailable, the app still starts and refresh will report the pipeline failure normally.

## MVP Scope

This version focuses on the information aggregator:

- default RSSHub sources
- canonical item normalization
- duplicate handling
- profile-based signal matching
- importance and relevance scoring
- daily top-signal output

It intentionally does not include a full ontology, production chat interface,
account system, long-term memory, or automatic action execution. The included
Agentic Core workbench is a local developer chat surface, not a production
multi-user chat product.

## Agentic Core Workbench

The Agentic Core is a local-only Python component served by the same FastAPI backend.

Create a local `.env` if one does not exist:

```bash
cp .env.example .env
```

Run the Web app command above, then open:

```text
http://127.0.0.1:4567/agent
```

Provider settings live at:

```text
http://127.0.0.1:4567/settings
```

The settings page writes provider API keys and `GITHUB_ACCESS_TOKEN` to `.env`.
It writes provider model/base URL choices to gitignored `config/agentic-core.local.yml`.
`config/agentic-core.example.yml` remains the committed default template.

The workbench reads existing pipeline artifacts such as `data/signals/latest.json` and writes agentic outputs under `data/agentic/`.

## Documentation

Start with `docs/index.md`.
