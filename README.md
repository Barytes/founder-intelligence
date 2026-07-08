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

The dashboard is written to:

- `data/dashboard/latest.md`
- `data/dashboard/latest.html`

## MVP Scope

This version focuses on the information aggregator:

- default RSSHub sources
- canonical item normalization
- duplicate handling
- profile-based signal matching
- importance and relevance scoring
- daily top-signal output

It intentionally does not include a full ontology, chat interface, account
system, long-term memory, or automatic action execution.

## Documentation

Start with `docs/index.md`.
