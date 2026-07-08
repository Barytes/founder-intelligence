# Ingestion Minimal Design

The ingestion step reads adapter output JSON and converts raw fetcher items into canonical items.

Current implementation:

- `src/ingest_adapter_output.rb`

Inputs:

- `data/adapter-output/rss-fetch-latest.json`
- `config/sources.yml`
- `config/ingestion-rules.yml`

Output:

- `data/canonical-items/latest.json`

Responsibilities:

- clean HTML from title, summary, content, and author fields
- collapse whitespace
- remove configured tracking query parameters from links
- normalize datetimes to ISO 8601 when possible
- generate `content_hash`
- generate provider-aware `dedupe_key`
- drop duplicate items within the same run
- add quality flags for missing optional fields

This step still does not persist to a database. The JSON output is a local artifact for validating the ingestion contract before storage is introduced.
