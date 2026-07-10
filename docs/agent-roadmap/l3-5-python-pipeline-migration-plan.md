# L3.5 Python Pipeline Migration Plan

本文说明 L3 tool contract 稳定之后，为什么以及如何把 Agent tool path 的 deterministic pipeline 迁移到 Python。当前分支已经完成 L3.5：`run_refresh_pipeline` 调用 Python-native runner，不再保留 Ruby wrapper。

## Why L3.5

L3 建立的是 Agent 可调用的稳定工具契约：

```text
read_signals
read_canonical_items
read_refresh_status
read_latest_run
run_refresh_pipeline
write_agentic_artifact
```

这些 tool names、provider-facing schemas 和 artifact contracts 应该保持稳定。底层实现可以迁移到 Python runner，但 Agent 不应该感知这次迁移。

L3.5 的核心目标是：

```text
same Agent tools
same artifact paths
same refresh status boundary
same failure protection
new Python-native pipeline implementation
```

## Current Implementation

当前 Agent refresh path：

```text
AgenticCore
-> ToolRegistry
-> run_refresh_pipeline
-> agentic_core.pipeline.runner.PipelineRunner
-> Python deterministic pipeline stages
-> data/app/refresh-status.json
-> data/signals/latest.json
```

Python package：

```text
src/agentic-core/agentic_core/pipeline/
  __init__.py
  fetch_rss.py
  ingest_adapter_output.py
  store_canonical_jsonl.py
  build_signals.py
  runner.py
```

职责：

- `fetch_rss.py`：RSS/Atom fetch and parser。
- `ingest_adapter_output.py`：adapter output -> canonical items。
- `store_canonical_jsonl.py`：append-only JSONL store and run record。
- `build_signals.py`：deterministic scoring and signal outputs。
- `runner.py`：lock、status、temp artifact、publish、failure preservation and CLI JSON status。

L3 初版曾设计过 transitional Ruby adapter。最新 `main` 已迁移到统一 Python backend，因此当前实现不再保留该 wrapper；自动化验证直接覆盖 Python-native runner。

## Migration Principles

1. Tool contracts stay stable.
2. Existing deterministic fixture behavior is the migration oracle until Python parity is proven.
3. Deterministic stages migrate before runner orchestration.
4. Artifact paths stay stable.
5. Failed refresh must not overwrite the previous successful signals.
6. Wrapper removal happens only after parity tests pass.

## Implemented Parity Coverage

`tests/test_python_pipeline_parity.py` covers:

- Python ingestion matches deterministic fixture behavior.
- Python store preserves append/dedupe/run-record behavior.
- Python signal build preserves ids, score rounding, ordering, tags, questions, risks, and summary count.
- Python fetch parser handles RSS and Atom fixtures.
- Python runner handles empty RSS source config without network.
- Python runner preserves previous successful signals on failure.
- Python runner module CLI emits JSON refresh status.

`tests/test_pipeline_tools.py` covers:

- `run_refresh_pipeline` calls Python-native `PipelineRunner`.
- Unknown arguments are rejected.
- Provider-facing schema remains stable.

`tests/test_python_pipeline_runner.py` and `tests/test_unified_web_app.py` cover the current Python Web app refresh path.

## Evaluation Gates

Required:

```bash
uv run --extra dev pytest -q
git diff --check
```

Focused:

```bash
uv run --extra dev pytest tests/test_python_pipeline_parity.py tests/test_pipeline_tools.py -q
```

Optional real RSS smoke:

```bash
docker compose -f config/docker-compose.yml up -d rsshub
PYTHONPATH=src/agentic-core uv run --extra dev python -m agentic_core.pipeline.runner --root .
```

Pass condition:

- Outputs are valid JSON.
- Failed refresh preserves previous successful signals.
- Any source/network difference is explicitly recorded instead of treated as parity success.

## Risks And Boundaries

### R1: Silent behavior drift

If Python output is only roughly similar, scores and signal ordering may drift.

Mitigation: exact parity tests for deterministic stages and runner failure behavior.

### R2: Web and Agent refresh entrypoints drift

The two callers must continue to use the same runner rather than reintroducing parallel refresh implementations.

Mitigation: `web_workbench.app` and `run_refresh_pipeline` both import `agentic_core.pipeline.runner.PipelineRunner`; unified API and pipeline tests cover that shared boundary.

### R3: Scope confusion

Python migration could be mistaken for L5 autonomous control.

Mitigation: keep L3.5 framed as implementation migration behind stable tools. L5 still requires planner, state, evaluator, stop condition, human handoff, and persistent trace.

## Completion Criteria

L3.5 is complete when:

- Python pipeline passes parity tests against deterministic fixture behavior.
- Python runner preserves lock, status, publish, and failure semantics for the Agent tool path.
- `run_refresh_pipeline` uses Python runner without changing provider-facing schema.
- Ruby wrapper is removed from the current integration.
- Docs identify Python runner as current Agent implementation.
