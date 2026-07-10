# Local JSONL Storage

The local storage layer writes canonical items to append-only JSONL files.

Current implementation:

- `src/agentic-core/agentic_core/pipeline/store_canonical_jsonl.py`

Input:

- `data/canonical-items/latest.json`

Output:

- `data/store/items/YYYY-MM-DD.jsonl`
- `data/store/runs/YYYY-MM-DD.jsonl`

Rules:

- one canonical item per JSONL line
- partition by local date
- append new items only
- skip duplicate `id` values already present in the partition file
- append a run summary for every store attempt
- do not mutate or rewrite existing item lines

This is not a database. It is a stable local handoff format before introducing a real persistence layer.

Example:

```bash
PYTHONPATH=src/agentic-core uv run python -m agentic_core.pipeline.runner --root .
```
