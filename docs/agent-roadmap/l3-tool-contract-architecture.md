# L3 Tool Contract Architecture

本文定义 Founder Intelligence 的 L3 目标架构：把当前确定性流程封装成 Agent 可调用、可审计、可验证的工具层。

L3 不是让 Agent 自主控制整个系统。L3 的目标是先建立稳定能力边界，让后续 L4 fixed workflow 和 L5 agentic controller 都调用同一套工具。

## 目标

L3 要让 Agentic Core 获得这些能力：

- 读取当前运行状态。
- 读取最近一次成功 signals。
- 读取最近一次 canonical items。
- 读取最近一次 store run。
- 触发一次受控 refresh。
- 写入 agentic artifact。

同时必须保留这些边界：

- 不让 Agent 执行任意 shell。
- 不让 Agent 直接修改 `config/`。
- 不让 Agent 启用 MCP/API/HTML source template。
- 不绕过 refresh runner 的锁、状态、产物校验和失败保护。
- 不让 LLM 读取 repo 内任意 JSON。

## 当前能力分布

当前 Ruby 主流程是：

```text
src/web/pipeline_runner.rb
  fetch_rss
  -> ingest_adapter_output
  -> store_canonical_jsonl
  -> build_signals
  -> publish data/signals/latest.json
```

当前 Python Agentic Core 是：

```text
src/agentic-core/agentic_core/
  core.py
  tools/registry.py
  tools/founder_tools.py
```

已有工具：

```text
read_signals
read_canonical_items
write_agentic_artifact
```

这些工具证明了 tool-calling loop 可运行，但工具面还不足以支撑 L4/L5，因为 Agent 还不能观察 refresh 状态或触发受控 pipeline。

## 新架构

L3 增加一个工具契约层：

```text
AgenticCore
  |
  v
ToolRegistry
  |
  +-- artifact tools
  |     read_latest_signals
  |     read_canonical_items
  |     read_latest_run
  |     read_refresh_status
  |     write_agentic_artifact
  |
  +-- workflow tools
        run_refresh_pipeline
```

L3.5 后，Agent tool 使用 Python-native runner 作为 refresh 执行器：

```text
run_refresh_pipeline tool
  |
  v
agentic_core.pipeline.runner.PipelineRunner
  |
  v
Python deterministic pipeline stages
  |
  v
data/app/refresh-status.json
data/signals/latest.json
```

L3 初版使用过固定 Ruby CLI wrapper：

```text
run_refresh_pipeline tool
  |
  v
fixed Ruby CLI wrapper
  |
  v
FounderIntelligence::Web::PipelineRunner#refresh
  |
  v
data/app/refresh-status.json
data/signals/latest.json
```

这个 fixed Ruby CLI wrapper 是早期设计方案，不是当前实现。最新 `main` 已迁移到统一 Python backend；L3.5 已在保持 `run_refresh_pipeline` tool contract 不变的前提下，把 Agent tool 底层执行器迁移为 Python-native runner。

这样 Agent 看到的是一个稳定 tool，而不是底层任意命令；未来迁移实现语言时，Agent-facing contract 不需要变化。

## Tool Contracts

Tool contracts are enforced in two places:

1. Provider-facing schemas tell the model which arguments are allowed.
2. `ToolRegistry.run` validates the supported schema subset before executing a handler.

This local validation is required because provider-side schema following is not a security boundary. At minimum, L3 must reject unknown arguments when `additionalProperties: false` is set, reject missing required arguments, and require object arguments for object tools.

### `read_refresh_status`

Purpose：读取 `data/app/refresh-status.json`。

Input：

```json
{}
```

Output when file exists：

```json
{
  "status": "succeeded",
  "started_at": "2026-07-09T10:00:00+08:00",
  "finished_at": "2026-07-09T10:00:05+08:00",
  "duration_seconds": 5.123,
  "current_step": null,
  "last_error": null,
  "store_summary": {
    "input_items": 20,
    "appended_items": 3,
    "skipped_duplicates": 17
  },
  "signal_diff": {
    "changed": true,
    "previous_count": 10,
    "current_count": 10,
    "added_ids": ["signal-new"],
    "removed_ids": ["signal-old"]
  }
}
```

Output when file is missing：

```json
{
  "status": "idle",
  "message": "No refresh status has been recorded yet."
}
```

Boundary：只读固定路径，不接受 path 参数。

### `read_latest_run`

Purpose：读取 `data/store/runs/*.jsonl` 中最新一条 run record。

Input：

```json
{}
```

Output：

```json
{
  "status": "ok",
  "path": "data/store/runs/2026-07-09.jsonl",
  "run": {
    "input_run_id": "rss-fetch-20260709T010000Z-abcd1234",
    "input_items": 20,
    "stored_items": 3,
    "skipped_duplicates": 17
  }
}
```

Boundary：只读 `data/store/runs/*.jsonl`。

### `read_latest_signals`

Purpose：读取最新成功 signals。

Input：

```json
{}
```

Output：`data/signals/latest.json` 原始 JSON。

Boundary：默认不接受 path 参数。为测试可以通过 tool context 传入 fixture path，但 provider-facing schema 不暴露 path。

### `read_canonical_items`

Purpose：读取最新 canonical items。

Input：

```json
{}
```

Output：`data/canonical-items/latest.json` 原始 JSON。

Boundary：默认不接受 path 参数。为测试可以通过 tool context 传入 fixture path，但 provider-facing schema 不暴露 path。

### `run_refresh_pipeline`

Purpose：触发一次完整 RSS-only refresh。

Input：

```json
{
  "reason": "User requested updated founder intelligence."
}
```

`reason` 只用于 trace，不影响命令构造。

Output：

```json
{
  "status": "succeeded",
  "request_id": "refresh-20260709T010000Z-abcd1234",
  "started_at": "2026-07-09T10:00:00+08:00",
  "finished_at": "2026-07-09T10:00:05+08:00",
  "duration_seconds": 5.123,
  "store_summary": {
    "input_items": 20,
    "appended_items": 3,
    "skipped_duplicates": 17
  },
  "signal_diff": {
    "changed": true,
    "previous_count": 10,
    "current_count": 10
  }
}
```

Boundary：

- 不接受 command、argv、path、script、source id 等参数。
- 调用 Python-native runner。
- 调用 `agentic_core.pipeline.runner.PipelineRunner.refresh`。
- 如果已有 refresh lock，返回 `already_running`，不强制释放。
- 如果 RSSHub 不可用，返回 runner 的 `failed` 状态，不覆盖上一版成功 signals。

### `write_agentic_artifact`

Purpose：写入 Agent 输出。

Input：

```json
{
  "final_text": "Markdown summary",
  "data": {
    "contract_version": 1,
    "kind": "l3_tool_run_note"
  }
}
```

Boundary：只允许写入 `data/agentic/`。

## 文件结构

当前新增或修改：

```text
src/agentic-core/agentic_core/pipeline/
src/agentic-core/agentic_core/tools/runtime_tools.py
src/agentic-core/agentic_core/tools/pipeline_tools.py
src/agentic-core/agentic_core/tools/__init__.py
config/agentic-core.example.yml
tests/test_runtime_tools.py
tests/test_pipeline_tools.py
tests/test_python_pipeline_parity.py
tests/test_tools.py
```

职责：

- `pipeline/`：Python-native deterministic pipeline stages 和 runner，是当前 Agent tool refresh path。
- `runtime_tools.py`：Python 只读 artifact/status tools。
- `pipeline_tools.py`：Python workflow tools，封装 Python-native runner 调用。
- `tools/__init__.py`：注册 provider-facing tool schemas。
- `config/agentic-core.example.yml`：声明新增 tools 的默认 enabled 状态。

## Why the Ruby wrapper was removed

L3 初版没有在 Python 里重写 refresh sequence，所以用固定 Ruby wrapper 建立了第一版 action boundary。

当时的原因：

- Ruby `PipelineRunner` 已经处理 lock、status、timeout、产物校验和失败保护。
- Python 重写会造成两个 refresh 语义，未来 Web app 和 Agent 容易分叉。
- L5 需要的是稳定 action boundary，不是重复实现 pipeline。

当时 Python tool 只允许调用固定 Ruby wrapper。这样它仍然是 Agent 工具，但执行语义来自现有主线。

L3.5 已按这个方向迁移：先建立 parity tests，再迁移 deterministic pipeline stages，最后把 `run_refresh_pipeline` 的底层实现切到 Python runner。迁移期间 tool contract 不变。由于最新 `main` 已删除旧 Ruby Web app runtime，继续保留 wrapper 会产生坏入口，因此当前集成移除了 wrapper。

因此当前边界是：

- Agent tool path：Python-native `agentic_core.pipeline.runner.PipelineRunner`。
- Web app path：Python `web_workbench.pipeline_runner.PipelineRunner`。
- Ruby wrapper：已移除。

## Permission Model

L3 tools 分为三类：

```text
read:  read_refresh_status, read_latest_run, read_latest_signals, read_canonical_items
run:   run_refresh_pipeline
write: write_agentic_artifact
```

当前不提供 config write tools。未来若需要，必须先增加：

- dry-run patch artifact。
- schema validation。
- human confirmation gate。
- rollback or previous-file backup。

## Trace Model

每个 tool result 应尽量包含：

```text
tool_name
status
artifact_paths
input_run_id
request_id
started_at
finished_at
duration_seconds
error_type
message
```

Agentic Core 已经记录 `ToolCallLog`，L3 先复用该结构。L5 前再升级为持久 run trace。

## L4/L5 Extension

L4 使用同一套 tools，但调用顺序固定：

```text
run_refresh_pipeline
read_latest_signals
read_canonical_items
write_agentic_artifact
```

L5 使用同一套 tools，但由 Agent 根据状态选择：

```text
read_refresh_status
-> decide whether refresh is needed
-> run_refresh_pipeline or read existing signals
-> inspect results
-> write artifact or ask human
```

因此 L3 是后续 L4/L5 的共同底座，不是一次性 demo 层。
