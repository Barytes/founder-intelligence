# L4 M8 Workflow、API 与当前 Dashboard 接入记录

日期：2026-07-12

状态：完成。

## 已实现

- `L4WorkflowRunner` 复用 `PipelineRunner` 的 refresh lock、status 文件、temp dir、atomic signal publish、last-success preservation 和清理语义；
- 新增独立 `FI_L4_WORKFLOW_ENABLED` gate；M9 默认切换前保持关闭；
- 固定步骤：

  ```text
  persist_events
  -> compile_resolve_profile
  -> decide_discover_sources
  -> resolve_source_snapshot
  -> collect
  -> ingest_store
  -> baseline_score
  -> agent_assess
  -> validate_compose
  -> publish
  -> trace
  ```

- 每步保存 sequence、status、input/output hash、时间、policy version 和脱敏错误；
- refresh status 增加 workflow_run_id、profile_id、source_snapshot_id、step_results、agent_stage_status、degraded_reasons 和 usage；
- profile/discovery/Agent failure 可降级继续；canonical/validation failure 禁止评分发布；publish failure 保留上一成功产物；
- Inbox canonical items 与 connector canonical items 在 ingestion 后去重合并；
- Agent ranking item failure 和 stage failure 均发布 deterministic fallback；
- Web `/api/refresh` 与 Agent `run_refresh_pipeline` 仍调用同一个 `PipelineRunner.refresh()` 入口，L4 gate 在 runner 内部统一委派；
- 当前三栏 dashboard 和新闻卡结构不变；左侧增加当前信息输入和 Inbox share；
- dashboard 展示 profile initialized/updated、tracking state、Agent degraded reason、workflow ID 和 score provenance；
- catalog source toggle 同时支持 legacy source ID 与自动发现的 target ID，不写回 YAML。

## 真实闭环 fixture

API integration test 在同一 FastAPI/SQLite/runner 实例中执行：

```text
POST /api/context/events
-> ProfileSnapshot active
-> POST /api/inbox/items
-> user_shared canonical item
-> POST /api/refresh
-> fixed L4 workflow
-> GET /api/signals/latest
-> profile/source/workflow linked hybrid-ranked Inbox signal
```

该测试不使用前端 mock；Profile/Assessment 使用 recorded typed output，fetch/ingestion 使用本地 fixture。

## Failure preservation

- live lock 存在时返回 `already_running`，不创建第二个 WorkflowRun；
- profile resolve failure 使用 neutral/baseline 路径，不修改 active pointer；
- discovery failure 继续使用既有 catalog snapshot；
- partial connector failure 与 item-level assessment failure 产生 `succeeded_partial`；
- canonical failure 的 trace 截止于 `ingest_store`，不会进入 baseline/Agent/publish；
- whole ranking adapter crash 回退 baseline；
- publish crash 不替换 `data/signals/latest.json`；
- status 的 last-success generated_at/input_run_id 与实际发布 artifact 一致。

## 证据

```text
M8 focused workflow/API: 10 passed
full suite: 229 passed
git diff --check: passed
```

W-01 至 W-12 均有 workflow、API 或既有 compatibility 自动测试证据。浏览器级 smoke、默认数据迁移、Inspector、rollback 和最终 SEC/A audit 进入 M9。
