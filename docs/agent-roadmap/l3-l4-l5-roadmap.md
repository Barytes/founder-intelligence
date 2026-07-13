# L3–L4–L5 Roadmap

## 当前状态：L4 implemented

L3 bounded tool contracts 与 L4 profile-driven fixed workflow 已实现：

```text
explicit user context
-> Profile Compiler
-> source discovery + local validation + probation
-> connector/Inbox canonical production
-> deterministic baseline
-> bounded evidence-backed Agent assessment
-> code-owned hybrid ranking
-> current dashboard + Inspector
```

PydanticAI 是唯一 Agent runtime；domain、repository、connector、workflow 和 policy 不依赖该框架。Web 与 Agent refresh 共享 runner lifecycle。Profile/source/ranking 各自有 fallback、trace、replay/rollback 和 kill switch。

旧 roadmap 中“RSS refresh 后生成末端 briefing”的直接 L4 方案属于历史备选，不是当前实现。Ruby refresh/dashboard 也已删除，不得作为 current truth。

## 当前 L4 边界

- workflow step order 由代码固定，Agent 不能自主改写；
- Agent 无权激活来源、修改 credential、设置 final score 或绕过 verifier；
- Search/connector/model failure 有 deterministic fallback；
- 只实现 RSS、RSSHub、Inbox connectors；
- 同步 refresh 保持本机 demo 简单，不包含 background/distributed execution；
- Inspector 不保存 chain-of-thought。

## L5 future gate

只有出现需要 Agent 自主选择步骤的真实用户任务，并且 L4 eval/成本/失败率稳定后，才进入 L5 controller。L5 必须新增：

- typed plan/stop/handoff contract；
- durable run state and resume；
- cross-step budget and loop prevention；
- high-risk human approval；
- scheduler/background worker boundary；
- controller-specific adversarial eval。

LangGraph 或 PydanticAI durable execution 只在跨进程 checkpoint、长时间暂停或分布式 worker 成为实际需求时评估；当前不为框架能力预先扩大架构。
