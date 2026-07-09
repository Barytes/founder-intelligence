# L3-L4-L5 Agentic Roadmap

本文说明 Founder Intelligence 从当前最小 Agentic Core 走向 L5/L6 的产品愿景和实现路径。

核心判断：下一阶段不应该只做一个接在 pipeline 末端的 AI 总结器，也不应该马上让 Agent 接管整个系统。更稳的路径是先建设 **L3 Tool Contract Layer**，再用它实现 **L4 Agent Workflow**，最后升级到 **L5 Agentic Controller**。

## 当前基线

当前系统由两部分组成：

1. Ruby deterministic pipeline：RSS fetch、ingestion、JSONL store、signal scoring、dashboard 输出。
2. Python Agentic Core：OpenAI-compatible provider、tool registry、tool-calling loop、本机 workbench。

当前 Agentic Core 已经能读取 `data/signals/latest.json`、读取 `data/canonical-items/latest.json`，并写入 `data/agentic/` artifact。但它还没有控制主 pipeline，也不负责 RSS 抓取、状态判断、失败恢复、配置修改或长期记忆。

因此，当前状态更像：

```text
deterministic pipeline
+ sidecar Agentic Core
```

目标状态不是把 deterministic pipeline 丢掉，而是把它逐步变成 Agent 可观察、可调用、可审计、可验证的工具环境。

## 愿景

长期目标是让 Agent 成为 Founder Intelligence 的流程控制核心：

```text
Observe
-> Plan
-> Choose tool
-> Act
-> Observe result
-> Reflect
-> Continue / Stop / Ask human
```

但这个目标需要有稳定工具边界作为底座。Agent 不应该直接获得任意 shell 权限，也不应该绕开当前 pipeline 的锁、状态文件、产物校验、失败保护和发布机制。

理想架构是：

```text
User / Scheduler / Web App
        |
        v
Agentic Controller
        |
        v
Tool Contract Layer
        |
        +-- refresh pipeline
        +-- read runtime status
        +-- read latest signals
        +-- inspect source health
        +-- validate config
        +-- build agent briefing
        +-- write artifacts
        |
        v
Deterministic Pipeline + Local Artifacts
```

其中 deterministic pipeline 继续承担可重复、可测试、低幻觉的计算；Agent 负责判断、编排、解释、复盘和人机交接。

## 直接 L4 方案

直接 L4 的做法是：保持当前 refresh runner 不变，在 `build_signals` 完成后调用 Agentic Core，生成 founder briefing。

数据流：

```text
RSS refresh
-> canonical items
-> deterministic signals
-> AgenticCore reads signals/items
-> AgenticCore writes data/agentic/latest.json and latest.md
-> Web app displays agent briefing
```

优点：

- 实现最快。
- 风险较低，Agent 只读结果、写分析。
- 能快速证明 runtime AI 对用户可见。
- 不需要立刻改造 pipeline runner。

缺点：

- Agent 只是末端分析器，不是流程参与者。
- 后续进入 L5 时仍要补做工具契约层。
- 很容易停留在“AI 总结卡片”，没有形成可持续 agent architecture。
- workflow 的可测试性主要集中在输出 schema，不能充分覆盖每个行动边界。

直接 L4 适合做短期演示，但不是最适合长期 L5/L6 的路线。

## L3-L4-L5 方案

推荐路径是先把现有流程封装成 Agent 可调用的 tools，再用这些 tools 实现固定 workflow，最后让 Agent 选择和控制 workflow。

### L3: Tool Contract Layer

L3 的重点不是做一个聊天界面，而是把系统能力整理成安全、窄权限、可测试的工具。

第一阶段工具应该偏 workflow-level：

```text
read_refresh_status
read_latest_run
read_latest_signals
read_canonical_items
run_refresh_pipeline
write_agentic_artifact
```

第二阶段再增加 step-level tools：

```text
fetch_rss
ingest_adapter_output
store_canonical_jsonl
build_signals
validate_sources_config
validate_profile_config
inspect_source_health
```

工具设计原则：

- 默认复用现有 `PipelineRunner`，不要让 Agent 直接执行任意 shell。
- 每个 tool 都要有 typed input、typed output、错误结构和权限边界。
- 所有写操作都要落入明确 allowlist。
- `config/` 修改默认只生成建议或 patch artifact，除非用户明确授权。
- 工具输出要包含足够 trace 信息，方便后续评测和复盘。

L3 完成标准：

- Agentic Core 可以通过 tools 读取运行状态、触发受控 refresh、读取最新结果、写分析 artifact。
- Web app 和 Agent 使用同一套 refresh/status 语义。
- 工具有单元测试或集成测试覆盖成功、失败、stale lock、产物缺失、JSON 损坏等情况。

### L4: Fixed Agent Workflow

L4 的重点是把 Agent 放入一个固定、可预测、可回放的 workflow 中。

推荐的最小 L4 workflow：

```text
run_refresh_pipeline
-> read_refresh_status
-> read_latest_signals
-> read_canonical_items
-> agent analyzes founder relevance, risks, actions
-> verifier checks schema and source references
-> write_agentic_artifact
-> Web app displays briefing
```

这一层仍然不是完全自主 Agent。流程顺序由系统固定，Agent 只在指定节点内做判断和生成。

L4 输出建议采用结构化 contract：

```text
generated_at
input_run_id
source_signal_ids
briefing_summary
priority_judgments[]
risks[]
recommended_actions[]
open_questions[]
confidence
tool_trace
```

L4 完成标准：

- 每次 refresh 后能生成稳定的 agent briefing。
- briefing 必须引用真实 signal id 或 canonical item id。
- schema 校验失败时不发布新 briefing。
- Agent 失败时不影响 deterministic signals 的发布。
- Web app 能区分 deterministic signals 和 agent analysis。

### L5: Agentic Controller

L5 的重点是让 Agent 控制流程，而不是只参与流程。

此时 Agent 可以根据状态自主选择：

```text
是否读取现有结果
是否触发 refresh
是否只分析某个 source/category
是否检查 source 健康
是否生成配置修改建议
是否向用户请求确认
是否停止
```

L5 loop：

```text
Goal
-> observe runtime status
-> inspect latest artifacts
-> make plan
-> call tools
-> observe tool results
-> update state
-> verify output
-> stop or ask human
```

L5 必须新增的系统能力：

- run state：记录 Agent 每次计划、行动、观察和结论。
- planner contract：要求 Agent 输出明确计划，而不是直接行动。
- evaluator/verifier：检查 schema、引用、权限、重复行动和停止条件。
- human handoff：高风险动作必须请求用户确认。
- budget/limit：限制 token、工具调用次数、refresh 次数和运行时长。
- failure taxonomy：区分 source failure、pipeline failure、model failure、schema failure、permission failure。

L5 完成标准：

- Agent 能在给定目标下完成 observe-plan-act-observe loop。
- Agent 可以在失败时解释原因，并选择重试、降级、停止或请求用户。
- 高风险动作不会绕过用户确认。
- 所有行动都有 trace，可以回放和评测。

## 两条路线对比

| 维度 | 直接 L4 | L3-L4-L5 |
| --- | --- | --- |
| 第一版速度 | 更快 | 稍慢 |
| 初始风险 | 更低 | 中等 |
| 用户可见价值 | 很快有 AI briefing | 需要先补工具层，但 briefing 更可靠 |
| 未来 L5 迁移 | 需要补做行动接口 | 顺滑升级 |
| 可测试性 | 主要测 briefing 输出 | 可以测试每个 tool 和 workflow |
| 可复用性 | 低，偏末端总结 | 高，Web、Agent、scheduler 可复用 |
| 架构可持续性 | 容易形成 sidecar AI | 更像 agent runtime foundation |
| 适合目标 | 快速演示 runtime AI | 长期 L5/L6 架构 |

结论：如果目标只是快速展示 AI 参与 runtime，直接 L4 足够；如果目标是让 Agent 未来控制整个流程，L3-L4-L5 更可扩展、更可持续。

## 推荐实施顺序

### Milestone 1: L3-min Tool Contracts

目标：让 Agent 可以安全调用现有主流程，而不是绕过它。

范围：

- 定义 tool input/output schema。
- 把 `PipelineRunner#refresh` 暴露为受控 tool。
- 增加 read-only runtime tools。
- 保持 `config/` 不被 Agent 自动修改。
- 写 tool contract 文档和测试。

### Milestone 2: L4-min Agent Briefing Workflow

目标：在固定 workflow 中生成 founder briefing。

范围：

- refresh 成功后触发 Agentic Core。
- 读取 signals/canonical items。
- 输出结构化 briefing artifact。
- 增加 verifier。
- Web app 展示 agent analysis。

### Milestone 3: L4 hardening

目标：让 L4 变成可稳定使用的产品能力。

范围：

- 加入成本、超时、重试、错误降级。
- 限制 tool 可读路径。
- 记录 tool trace。
- 增加 golden fixture 评测。
- 区分 deterministic result 和 agent judgment。

### Milestone 4: L5 bounded controller

目标：让 Agent 在 guardrails 内选择流程动作。

范围：

- Agent run state。
- Planner/evaluator loop。
- Stop condition。
- Human confirmation gate。
- Proactive run proposal，而不是无约束自动执行。

## 与 L6 的关系

L6 的三个方向可以在 L3-L5 中逐步铺设：

frictionless interaction：

- L4 阶段自动生成 briefing，减少用户复制粘贴和手动提问。
- L5 阶段根据状态主动提出下一步，而不是等待用户打开 chat。

contextual intelligence：

- L3 阶段把 profile、rules、latest run、signals、source health 变成可读 tools。
- L4 阶段把这些上下文固定注入 workflow。
- L5 阶段让 Agent 根据目标动态选择上下文。

proactive intelligence：

- L4 阶段只生成建议和 open questions。
- L5 阶段可以提出 refresh、source check、配置修改建议。
- 真正写配置或外部行动必须有人类确认。

## 不做什么

短期内不做：

- 不让 Agent 执行任意 shell。
- 不让 Agent 自动修改 `config/`。
- 不把 MCP/API/HTML source template 当作已实现 fetcher。
- 不做无状态的“聊天问答”替代工具层。
- 不把 L5 宣称建立在没有 trace、verifier、stop condition 的 loop 上。

## 架构原则

1. Deterministic pipeline remains the spine.
2. Tools are contracts, not shortcuts.
3. Agent judgment must be traceable to local artifacts.
4. Fixed workflow comes before autonomous control.
5. Human confirmation gates protect high-risk writes.
6. Evaluation must cover both output quality and action safety.

这条路线的关键不是尽快让 Agent “看起来能做很多事”，而是让每个可做的事都有清晰边界、可验证产物和可复盘记录。这样 L4 不会变成一次性 AI 卡片，L5 也不会变成不可控的黑箱流程。
