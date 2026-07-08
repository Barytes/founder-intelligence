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

`rss` fetchers read `connection.rss_url`, usually from RSSHub.

`mcp` fetchers call a named tool such as `xiaohongshu-mcp` or `wechat-mcp`. These are expected to handle platform-specific auth and may return cursors.

`api` fetchers call HTTP APIs directly. They should expose native ids and pagination state without doing final normalization.

`html` fetchers scrape pages using selectors. They should be treated as fragile and must report selector failures explicitly.

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

## Next Implementation Step

When code starts, define a single `FetcherAdapter` interface first, then implement the RSS adapter before MCP/API/HTML adapters. RSSHub is already running locally, so RSS is the lowest-risk first implementation target.

The first local implementation is `src/fetch_rss.rb`. It reads enabled RSS sources from `config/sources.yml`, fetches RSSHub XML, and writes adapter output JSON without applying final ingestion normalization.
