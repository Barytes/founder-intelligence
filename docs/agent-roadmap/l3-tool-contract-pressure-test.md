# L3 Tool Contract Pressure Test

本文 pressure-tests 两个方案：

1. `l3-tool-contract-architecture.md`
2. `l3-tool-contract-implementation-plan.md`

目标是检查需求理解偏差、reward-hack 空间、安全边界、可维护性和未来 L4/L5 可扩展性。每个漏洞都附带修正方案；修正已反映到当前架构和实现计划中。

## Iteration 1 Findings

### P1: Python 直接重写 refresh sequence 会制造第二条主流程

Problem：

如果 `run_refresh_pipeline` 在 Python 中直接调用：

```text
fetch_rss
ingest_adapter_output
store_canonical_jsonl
build_signals
```

就会绕开 runner 中已有的 lock、status、产物校验、失败保护、发布语义和日志脱敏。

Risk：

- Web app refresh 和 Agent refresh 行为分叉。
- L5 复盘时无法判断状态文件是否可信。
- 失败时可能覆盖上一版成功 signals。

Fix：

- L3 初版先避免直接拼接 step-level command。
- L3.5 已补上 Python parity tests，再把 deterministic pipeline 迁移为 `agentic_core.pipeline.runner.PipelineRunner`。
- 当前 Agent tool path 调用 Python-native runner，不再保留 Ruby wrapper。

Status：closed。

### P1: Provider-facing path 参数会让模型读取 repo 内任意 JSON

Problem：

当前 `read_signals` 和 `read_canonical_items` 接收 `path` 参数。虽然会禁止 repo 外路径，但 repo 内仍可能存在不该给模型读取的 JSON。

Risk：

- Prompt injection 后模型可尝试读取 repo 内其他 JSON。
- 后续如果 `.env` 或 local config 被误写成 JSON，风险扩大。

Fix：

- L3 provider-facing schema 改为 no-arg。
- 测试上下文仍可注入 fixture path，但模型不能传 path。
- 实现计划 Task 6 已加入 schema 收窄。

Status：closed。

### P1: `run_refresh_pipeline` 如果接受参数，会退化成任意命令入口

Problem：

如果 refresh tool 接受 `command`、`argv`、`script`、`path`、`source_id` 等参数，Agent 工具层会复制 Web app 曾经避免的任意命令风险。

Risk：

- 模型或注入内容可构造非预期命令。
- L3 还没到 L5 就引入高危行动面。

Fix：

- `run_refresh_pipeline` 只接受可选 `reason`。
- `reason` 只进入 trace，不参与命令构造。
- Python tool 对 unknown args 返回 `invalid_arguments`。
- Provider schema 使用 `additionalProperties: False`。

Status：closed。

### P1: 只收窄 provider schema 不足以阻止恶意 tool arguments

Problem：

当前 `ToolRegistry` 会把 schema 暴露给 provider，但本地执行前没有校验 arguments。如果模型或兼容 provider 返回了 schema 外字段，handler 仍会收到这些字段。

Risk：

- `read_signals` 即使 provider schema 不暴露 `path`，也可能收到模型构造的 `path`。
- `run_refresh_pipeline` 即使 schema 禁止 `command`，也可能收到未知参数。

Fix：

- 实现计划新增 Task 4，在 `ToolRegistry.run` 中执行本地 schema subset validation。
- 对 `additionalProperties: False`、`required` 和 object 类型做最小校验。
- Evaluation plan 要求 `ToolInvalidArgumentsError` 覆盖 unknown args。

Status：closed。

### P2: 只规划工具，不规划评测，会让 L3 看起来完成但不可证明

Problem：

工具层的风险主要在边界，不在 happy path。如果只测“能调用”，无法证明它适合 L4/L5。

Risk：

- Reward hack：注册了 tool，但 tool 可以绕过权限。
- Reward hack：tool 调用了 runner，但没有确认 Python runner 与旧确定性流程保持关键语义一致。

Fix：

- 新增 `l3-tool-contract-evaluation-plan.md`。
- 每个 acceptance criterion 都包含 command、pass condition、reward-hack risk 和 countermeasure。
- 新增 `tests/test_python_pipeline_parity.py` 覆盖 deterministic pipeline parity。

Status：closed。

### P2: Tool 粒度过细会让 L3 变成脆弱 shell wrapper 集合

Problem：

如果第一版直接暴露 `fetch_rss`、`ingest_adapter_output`、`store_canonical_jsonl`、`build_signals`，Agent 可能以错误顺序调用 step-level tools。

Risk：

- L4 还没建立 verifier，就出现不完整运行状态。
- L5 前过早暴露过多行动组合。

Fix：

- Milestone 1 只实现 workflow-level `run_refresh_pipeline`。
- Step-level tools 延后到 L4 hardening 或 L5 bounded controller 前。
- 架构文档保留 step-level tools 为第二阶段。

Status：closed。

### P2: 没有 config write 策略会让未来 L5 卡住

Problem：

L5 最终会想修改 sources/profile，但 L3 若直接排除 config tools，未来可能需要重构。

Risk：

- L3 太保守，无法自然通往 L5。
- 后续临时加入 config write tool 时缺少审批模型。

Fix：

- L3 明确不做 config write。
- 架构中定义未来 config write 前置条件：
  - dry-run patch artifact。
  - schema validation。
  - human confirmation gate。
  - rollback or previous-file backup。

Status：closed。

## Iteration 2 Findings

### P1: Real RSS smoke 如果进入自动测试，会变成不稳定外部依赖

Problem：

真实 refresh 若默认进入自动测试，会依赖 RSSHub、网络和 source 状态。

Risk：

- 本地 CI 不稳定。
- 设计文档把可选 smoke 当成必需测试。

Fix：

- Automated acceptance 主要测试 Python runner behavior 和 Python pipeline parity。
- 真 RSSHub refresh 只作为 optional manual smoke。
- Evaluation plan 已区分 automated gate 和 Docker/RSSHub optional smoke。

Status：closed。

### P2: 只用 monkeypatch 测 Python runner path，不能证明完整 refresh 语义

Problem：

Python tool 测试可以证明 `run_refresh_pipeline` 调用了 Python runner，但不能单独证明 Python runner 与旧 Ruby stages 的关键语义保持一致。

Risk：

- Tool test 通过，但 Python pipeline 在 ingestion、store、signal build 或失败保护上和期望确定性语义分叉。

Fix：

- `tests/test_pipeline_tools.py` 覆盖 Agent tool 调用 Python runner。
- `tests/test_python_pipeline_parity.py` 覆盖 ingestion、store、signal build、RSS/Atom parser、runner success/failure/CLI。
- `tests/test_python_pipeline_runner.py` 和 `tests/test_unified_web_app.py` 继续覆盖当前 Web app refresh path。

Status：closed。

### P2: `repo_root` context 如果暴露给 provider，会成为路径注入

Problem：

测试需要 `repo_root` context 注入，但 provider-facing schema 不能暴露它。

Risk：

- Agent 可以把 root 指向其他目录。

Fix：

- `repo_root` 只存在 Python caller context，不进入 provider tool schema。
- Provider-facing schemas 不包含 `repo_root`。
- Tests use direct handler invocation or registry context injection。

Status：closed。

### P3: L3 completion 容易被误判为 L5

Problem：

实现工具层后，Agent 可以触发 refresh，但这不等于 L5 controller。

Risk：

- 文档和产品叙述夸大当前能力。
- 缺少 planner、state、evaluator、stop condition 就宣称 Agentic Core 控制流程。

Fix：

- Architecture document 明确 L3 is tool layer, not autonomous control。
- Roadmap 保留 L4/L5 边界。
- Evaluation plan 不把 autonomous planning 纳入 L3 acceptance。

Status：closed。

## Open Issues

No blocking issues remain in the architecture or implementation plan after Iteration 2.

Known future work remains intentionally out of L3/L3.5 scope:

- Optional cleanup: unify the Web app runner and Agent tool runner after user approval。
- L4 briefing verifier。
- Persistent Agent run trace。
- Config patch proposal and human confirmation。
- Step-level source health inspection。
- Real scheduler/proactive runs。

These are not L3 plan holes because the current plan explicitly scopes L3 to controlled observation and refresh tools.

## Final Recommendation

当前实现可以作为 L3/L3.5 的最小可用改进继续推进到 L4。后续进入 L4/L5 前，仍需确认：

1. L3 tool list。
2. Python runner as the current Agent tool path。
3. No config write in L3。
4. Evaluation gate。

The plan is now aligned with the long-term L5 goal because it creates reusable action contracts without prematurely granting autonomous control.
