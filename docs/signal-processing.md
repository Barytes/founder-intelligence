# Signal Processing MVP

This layer turns canonical items into user-facing intelligence signals.

Current implementation:

- `src/agentic-core/agentic_core/pipeline/build_signals.py`

Inputs:

- `data/canonical-items/latest.json`
- `config/user-profile.yml`
- `config/signal-rules.yml`

Outputs:

- `data/signals/latest.json`
- `data/dashboard/latest.md`
- `data/dashboard/generated-latest.html`

Responsibilities:

- detect product and market themes with keyword rules
- match items against the user profile, goals, interests, watched entities, and negative preferences
- score item importance from source priority, recency, theme matches, and content depth
- score personal relevance from profile keyword matches and exclusions
- generate a fixed decision-support card for each top signal:
  - what happened
  - why it matters
  - why it is relevant to the user
  - follow-up questions
  - risks or counterpoints
  - source link

This is intentionally deterministic for MVP validation. It does not call an LLM.
The next version can replace `what_happened`, relevance reasoning, and follow-up
questions with an LLM while keeping the same JSON contract.

Example:

```bash
PYTHONPATH=src/agentic-core uv run python -m agentic_core.pipeline.runner --root .
```
