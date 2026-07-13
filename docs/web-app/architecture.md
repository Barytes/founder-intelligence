# 当前 Web App 架构

FastAPI `web_workbench.app` 是统一本机 HTTP 服务；`src/web/public/` 保留原三栏信号控制台，Agent/Settings/Inspector 位于 `src/agentic-core/web_workbench/static/`。

## Pages

- `/`：当前信息输入、Inbox share、来源 tracking、新闻优先队列、score provenance 和 degraded indicator；
- `/agent`：bounded Agent chat/tool view；
- `/settings`：provider/local secret；
- `/inspector`：run timeline、profile/source/score provenance、replay 和 kill switches。

## L4 APIs

```text
POST/GET /api/context/events
GET      /api/profile/current
GET      /api/profile/history
POST/GET /api/inbox/items
GET      /api/sources
POST     /api/sources/:id
POST     /api/refresh
GET      /api/refresh/status
GET      /api/signals/latest

GET      /api/inspector/runs
GET      /api/inspector/runs/:id
POST     /api/inspector/runs/:id/replay
POST     /api/inspector/rollback/profile
POST     /api/inspector/rollback/source
POST     /api/inspector/controls/:stage
```

所有 mutating API—including chat、refresh、context、Inbox、source toggle、rollback、replay 和 kill switch—执行相同 same-origin policy。Refresh 不接受 command/script/path/argv/args。

## Source/profile truth

- `/api/profile/current` 读取 SQLite ProfileStore；当前信息通过 context event 更新。
- `/api/profile` 只暴露一个发布周期的 legacy YAML adapter，并明确返回 `source_of_truth=legacy_compatibility`。
- `/api/sources` 默认读取 SQLite SourceCatalog；legacy YAML PUT 是显式 semantic import，不回写 runtime status。

## Refresh

Web 和 Agent tool 进入同一 `PipelineRunner.refresh()`。L4 workflow 继续复用 lock、status、temp dir 和 atomic publish。Status 暴露 workflow/profile/source IDs、exact step results、Agent state、degraded reasons 和 usage summary。页面只读取真实 API，不维护 mock source/profile 状态。

当前服务没有远程身份认证，应只绑定 localhost。

新闻详情会直接展示安全的 AgentAssessment 五维结果、`reasoning_summary`、
原文 evidence spans、baseline/final score 和排序变化；fallback 时展示真实原因。
这些字段来自已发布 signal，不由前端重新推断。
