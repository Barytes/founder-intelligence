# Fetcher Adapter Design

This project separates source fetching from ingestion.

Fetchers only retrieve source-native items and return a stable adapter response. The ingestion layer then applies `config/ingestion-rules.yml` for field mapping, cleanup, deduplication, hashing, and quality gates.

## Adapter Inputs

Every fetcher receives:

- `source`: one entry from `config/sources.yml`
- `context`: run metadata such as `run_id`, `fetched_at`, optional cursor, timeout, and max item count

The fetcher must not read unrelated sources or mutate source configuration.

## Adapter Outputs

Every fetcher returns:

- `source_id`
- `source_type`
- `provider`
- `fetched_at`
- `status`: `ok`, `partial`, `failed`, or `skipped`
- `items`: raw items ready for canonicalization
- `errors`: structured source-level or item-level errors

Optional fields include `next_cursor`, `rate_limit`, and `raw_feed_metadata`.

## Source Types

`rss` fetchers read `connection.rss_url`, usually from RSSHub. This is the only implemented fetch path today.

`mcp` fetchers would call a named tool such as `xiaohongshu-mcp` or `wechat-mcp`. These are design templates only; no runnable MCP fetcher exists in the current code.

`api` fetchers would call HTTP APIs directly. They should expose native ids and pagination state without doing final normalization. No runnable API fetcher exists in the current code.

`html` fetchers would scrape pages using selectors. They should be treated as fragile and must report selector failures explicitly. No runnable HTML fetcher exists in the current code.

## Boundary

Fetcher responsibilities:

- connect to the source
- authenticate when required
- fetch items
- expose platform-native ids
- return raw payloads when allowed
- report structured errors

Ingestion responsibilities:

- map fields into canonical item shape
- normalize datetimes and links
- strip or preserve HTML according to rules
- generate hashes
- deduplicate
- apply quality gates

## Current Implementation

The current local implementation is `src/agentic-core/agentic_core/pipeline/fetch_rss.py`. It reads enabled RSS sources from `config/sources.yml`, fetches RSSHub XML, and writes adapter output JSON without applying final ingestion normalization.

Future MCP/API/HTML adapters should conform to the same adapter output shape before being wired into the main refresh path.
