# Python-Only Refresh Migration

## Requirement

Remove the unused Ruby source-dashboard generator, make browser and Agent refresh use the same Python-native pipeline, and remove the Ruby refresh scripts only after the Python implementation is verified.

## Implementation

1. Import `agentic_core.pipeline.runner.PipelineRunner` from the FastAPI app.
2. Preserve the current `display_title` and `display_summary` output fields in the Python signal builder.
3. Replace Ruby-parity and Ruby-wrapper tests with Python output-contract and unified-runner tests.
4. Delete the Ruby dashboard helper, four Ruby refresh scripts, and the old subprocess runner after tests pass.
5. Update runtime documentation so it names the Python pipeline as the only implemented refresh path.

## Evaluation

- `uv run --extra dev pytest -q` passes without Ruby installed or invoked.
- `git diff --check` passes.
- A real RSSHub refresh reports all enabled sources through `adapter_summary`.
- `/api/refresh` uses the same Python runner class as `run_refresh_pipeline`.
