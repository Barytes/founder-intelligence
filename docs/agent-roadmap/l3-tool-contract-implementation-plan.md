# L3/L3.5 Agent Tool Contracts Implementation Plan

本文记录当前已实施的 L3 tool layer 和 L3.5 Python pipeline migration。它是后续维护者的执行依据，不再保留早期 Ruby wrapper 作为主路径的任务清单。

## Goal

L3 的目标是让 Agentic Core 可以安全地观察运行状态、读取产物、触发一次受控 refresh，并写入 agentic artifact。

L3.5 的目标是在不改变 provider-facing tool contract 的前提下，把 `run_refresh_pipeline` 背后的执行器从 Ruby wrapper 迁移为 Python-native deterministic pipeline。

这两个目标仍然不是 L5。当前系统还没有自主 planner、evaluator、stop condition、human handoff 和持久 trace；它只是为 L4/L5 提供稳定工具边界。

## Current Architecture

```text
AgenticCore
  -> ToolRegistry
     -> read tools
        read_signals
        read_canonical_items
        read_refresh_status
        read_latest_run
     -> workflow tool
        run_refresh_pipeline
          -> agentic_core.pipeline.runner.PipelineRunner
             -> fetch_rss
             -> ingest_adapter_output
             -> store_canonical_jsonl
             -> build_signals
     -> write tool
        write_agentic_artifact
```

L3 初版曾计划使用 Ruby transitional adapter。最新 `main` 已迁移到统一 Python backend，因此当前实现不再保留 Ruby wrapper；Agent tool path 只调用 Python-native runner。

## Implemented Files

L3 tool layer:

- `src/agentic-core/agentic_core/tools/runtime_tools.py`
- `src/agentic-core/agentic_core/tools/pipeline_tools.py`
- `src/agentic-core/agentic_core/tools/registry.py`
- `src/agentic-core/agentic_core/tools/__init__.py`
- `config/agentic-core.example.yml`

L3.5 Python pipeline:

- `src/agentic-core/agentic_core/pipeline/fetch_rss.py`
- `src/agentic-core/agentic_core/pipeline/ingest_adapter_output.py`
- `src/agentic-core/agentic_core/pipeline/store_canonical_jsonl.py`
- `src/agentic-core/agentic_core/pipeline/build_signals.py`
- `src/agentic-core/agentic_core/pipeline/runner.py`

Tests:

- `tests/test_runtime_tools.py`
- `tests/test_pipeline_tools.py`
- `tests/test_python_pipeline_parity.py`
- `tests/test_tools.py`

Docs:

- `docs/agent-core/index.md`
- `docs/agent-roadmap/l3-l4-l5-roadmap.md`
- `docs/agent-roadmap/l3-tool-contract-architecture.md`
- `docs/agent-roadmap/l3-tool-contract-evaluation-plan.md`
- `docs/agent-roadmap/l3-tool-contract-pressure-test.md`
- `docs/agent-roadmap/l3-5-python-pipeline-migration-plan.md`

## Provider-Facing Contracts

`read_signals` and `read_canonical_items` expose no `path` argument to the model. Test code can still inject fixture paths through tool context, but provider-facing schema does not allow arbitrary repo JSON reads.

`run_refresh_pipeline` accepts only:

```json
{
  "reason": "optional human-readable trace reason"
}
```

It rejects `command`, `argv`, `script`, `path`, `source_id`, and all unknown arguments before execution. `reason` never affects command construction or file paths.

`ToolRegistry.run` performs local schema subset validation before invoking handlers. Provider-side schema following is treated as a convenience, not a security boundary.

## Python Pipeline Semantics

The Python runner preserves the required refresh semantics for the Agent tool path:

- fixed RSS-only source loading from repo config;
- lock file prevents concurrent refresh;
- status file records running, succeeded, succeeded_empty, already_running, and failed states;
- canonical store is append-only and deduplicated by source/id/url/title;
- signal build produces deterministic JSON/Markdown/HTML artifacts;
- failed refresh preserves the previous successful `data/signals/latest.json`;
- module CLI emits a JSON status payload.

The Web app and Agent tool path both use `agentic_core.pipeline.runner.PipelineRunner`; the FastAPI route and Agent tool differ only in their caller boundary.

## Verification

Required automated gates:

```bash
uv run --extra dev pytest -q
git diff --check
```

Focused gates:

```bash
uv run --extra dev pytest tests/test_runtime_tools.py tests/test_pipeline_tools.py -q
uv run --extra dev pytest tests/test_python_pipeline_parity.py -q
uv run --extra dev pytest tests/test_tools.py::test_default_registry_exposes_l3_runtime_tools -q
```

Optional manual smoke with provider credentials:

```bash
PYTHONPATH=src/agentic-core uv run python -m agentic_core.run --config config/agentic-core.example.yml --prompt "Read the latest refresh status and latest signals, then write a short artifact."
```

Pass condition: the tool trace uses only registered tools, and any artifact is written under `data/agentic/`.

## Out Of Scope

The current L3/L3.5 implementation intentionally does not add:

- autonomous L5 planning;
- model-chosen tool sequences beyond the existing core loop;
- config write tools;
- MCP/API/HTML fetchers;
- arbitrary shell execution;
- multi-agent orchestration;
- unifying the Web app runner and Agent tool runner into one shared implementation.

## Next Step Toward L4/L5

L4 should reuse the same tools in a fixed workflow:

```text
read_refresh_status
-> run_refresh_pipeline if needed
-> read_signals
-> read_canonical_items
-> write_agentic_artifact
```

L5 should add controller capabilities around the same tool contracts:

```text
goal -> observe -> plan -> choose tool -> act -> observe -> verify -> continue/stop/ask human
```

The important architectural choice is that L4 and L5 should not create new refresh paths. They should call the stable L3 tools and evolve planner/state/evaluator layers around them.
