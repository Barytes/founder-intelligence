# L3 Tool Contract Evaluation Plan

本文定义 L3 Agent tool layer 的测评方案。目标不是证明 Agent 生成文本更聪明，而是证明 tool layer 安全、稳定、可测试，并能成为 L4/L5 的底座。

## Evaluation Scope

L3 评测覆盖：

- Tool contract correctness。
- Permission boundary。
- Runtime artifact reading。
- Refresh runner integration。
- Failure handling。
- Existing Web app compatibility。
- L4/L5 extensibility readiness。
- Python runner boundary checks。

不覆盖：

- LLM 输出质量。
- L4 briefing 内容质量。
- L5 autonomous planning。
- MCP/API/HTML fetcher。

## Acceptance Criteria

### A1: Read-only tools use fixed artifact paths

Evidence：

```bash
uv run --extra dev pytest tests/test_runtime_tools.py -q
uv run --extra dev pytest tests/test_tools.py::test_read_artifact_tools_do_not_expose_path_arguments_to_provider -q
```

Pass condition：

- `read_refresh_status` reads only `data/app/refresh-status.json`。
- `read_latest_run` reads only `data/store/runs/*.jsonl`。
- Provider-facing `read_signals` and `read_canonical_items` schemas expose no `path` argument。

Reward-hack risk：

- Test passes because provider schema is hidden, but handler still accepts arbitrary model-supplied `path` through arguments.

Countermeasure：

- Add local registry validation and a test that `registry.run("read_signals", {"path": "/tmp/x"}, context)` raises `ToolInvalidArgumentsError` before handler execution.

### A2: Refresh tool cannot execute arbitrary commands

Evidence：

```bash
uv run --extra dev pytest tests/test_pipeline_tools.py -q
```

Pass condition：

- `run_refresh_pipeline` rejects `command`, `argv`, `script`, `path`, and unknown arguments。
- It calls Python-native `agentic_core.pipeline.runner.PipelineRunner` with the repo root from local context。
- It does not expose command, cwd, source id, script, or config path to provider-facing arguments。
- `ToolRegistry.run` enforces `additionalProperties: False` before handler execution.

Reward-hack risk：

- Test monkeypatch checks runner invocation but implementation later adds optional dangerous args.

Countermeasure：

- Include an explicit unexpected-argument rejection test.
- Keep provider schema with `additionalProperties: False`。

### A3: Refresh tool reuses PipelineRunner semantics

Evidence：

```bash
uv run --extra dev pytest tests/test_pipeline_tools.py tests/test_python_pipeline_parity.py -q
uv run --extra dev pytest tests/test_python_pipeline_runner.py tests/test_unified_web_app.py -q
```

Pass condition：

- Agent tool invokes Python-native `agentic_core.pipeline.runner.PipelineRunner`。
- Python parity and current Web app runner tests still pass:
  - successful refresh publishes validated temp signals。
  - failed refresh preserves previous successful signals。
  - lock prevents concurrent refresh。

Reward-hack risk：

- Python tool bypasses the runner and reimplements the step sequence inside the tool handler.

Countermeasure：

- `tests/test_pipeline_tools.py` asserts the Python runner path.
- L3.5 parity tests cover Python-native pipeline behavior against deterministic fixtures.

### A4: L3 tools are visible to Agentic Core

Evidence：

```bash
uv run --extra dev pytest tests/test_tools.py::test_default_registry_exposes_l3_runtime_tools -q
```

Pass condition：

- `read_refresh_status`
- `read_latest_run`
- `run_refresh_pipeline`

appear in `ToolRegistry.provider_tools()` when enabled.

Reward-hack risk：

- Tools are registered but disabled in `config/agentic-core.example.yml`。

Countermeasure：

- Check `config/agentic-core.example.yml` includes enabled entries.

### A5: PydanticAI Agentic Core contract still works

Evidence：

```bash
uv run --extra dev pytest tests/test_core_loop.py -q
uv run --extra dev pytest tests/test_workbench_api.py -q
```

Pass condition：

- PydanticAI runtime records tool calls through `ToolRegistry`。
- Tool errors are surfaced as tool messages。
- Artifact paths are still aggregated。
- Workbench chat still calls Agentic Core.

Reward-hack risk：

- New tools pass isolated tests but break provider tool schema serialization.

Countermeasure：

- Run full Python test suite.

### A6: Existing Web app behavior is unchanged

Evidence：

```bash
uv run --extra dev pytest tests/test_unified_web_app.py tests/test_python_pipeline_runner.py -q
```

Pass condition：

- `/api/refresh` still rejects command parameters。
- Web app refresh still calls runner once。
- Profile/source edit validation behavior is unchanged。

Reward-hack risk：

- L3.5 gives Agent and Web app separate Python runner implementations that could drift.

Countermeasure：

- Keep Web app tests and Python runner parity tests green until the two runner implementations are unified separately.

## Manual Smoke

After automated tests pass, run:

```bash
PYTHONPATH=src/agentic-core uv run python -m agentic_core.run --config config/agentic-core.example.yml --prompt "Read the latest refresh status and latest signals, then write a short artifact."
```

Pass condition：

- If no API key is configured, the command should return a clear provider/config error without changing pipeline artifacts.
- If an API key is configured, the tool trace should show only registered tools and any artifact should be under `data/agentic/`.

This manual smoke is optional for local development without provider credentials. It cannot replace unit and integration tests.

## Completion Gate

L3 is not complete until these commands pass:

```bash
uv run --extra dev pytest -q
git diff --check
```

If Docker/RSSHub is available, add one real refresh smoke:

```bash
docker compose -f config/docker-compose.yml up -d rsshub
PYTHONPATH=src/agentic-core uv run --extra dev python -m agentic_core.pipeline.runner --root .
```

Pass condition for real refresh smoke：

- Output is valid JSON。
- Status is `succeeded`, `succeeded_empty`, or an explainable `failed` caused by source/network availability。
- Existing `data/signals/latest.json` is not overwritten on failure。
