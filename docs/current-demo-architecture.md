# 当前 L4 Runtime 架构

Founder Intelligence 当前默认运行形态是 profile-driven fixed workflow，不是末端 AI briefing，也不是完全自主 controller。

## 用户闭环

```text
显式用户信息 / correction / follow / share
-> UserContextEvent
-> PydanticAI Profile Compiler
-> immutable ProfileSnapshot / EffectiveProfile
-> deterministic source-discovery due decision
-> SearchProvider + typed candidate Agent
-> local URL/connector/quality validation
-> probation SourceTarget / AcquisitionBinding
-> collect + Inbox canonical ingestion
-> deterministic baseline score
-> bounded candidate pool
-> evidence-backed News Assessment Agent
-> code-owned hybrid score and priority queue
-> 当前三栏 dashboard
```

固定 step order 定义在 `agentic_core.l4.workflow.L4_STEP_ORDER`。Web `POST /api/refresh` 与 Agent tool `run_refresh_pipeline` 都进入 `PipelineRunner.refresh()`；runner 在 L4 gate 开启时委派 `L4WorkflowRunner`，继续复用既有 lock、status、temp dir 和 atomic publish。

## 启动

```bash
docker compose -f config/docker-compose.yml up -d rsshub
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

页面：

- `/`：信号控制台；
- `/agent`：Agent Workbench；
- `/settings`：本机 provider/secret 配置；
- `/inspector`：workflow、profile、source、score、replay 和 kill-switch 开发者视图。

## Source of truth

- `data/app/founder-intelligence.db`：events、profiles、source catalog/snapshots、discovery trace、assessments、workflow trace 和 runtime controls。
- `data/canonical-items/latest.json`：当前 canonical handoff。
- `data/store/**/*.jsonl`：canonical append-only export/handoff。
- `data/signals/latest.json`：atomic published latest-success dashboard artifact。
- `data/app/refresh-status.json`：当前/最近 refresh 状态。

`config/sources.yml` 已 semantic import 并保留 byte-identical backup。`config/user-profile.yml` 不会导入 ProfileStore；`config/user-profile.example.yml` 只展示格式。

自动发现产生的 native RSS/RSSHub binding 会在 snapshot boundary 转为现有 collector contract，并保留 target/binding provenance 与 probation item quota；因此 discovery source 与 YAML bootstrap source 使用同一真实 collect/ingest 主线。

## 失败与回滚

- profile/discovery/Agent failure 有明确 deterministic fallback；
- 单 connector failure 可 `succeeded_partial`；
- canonical failure 不进入 scoring/publish；
- publish failure 保留上一成功 signals；
- Inspector replay 不调用外部依赖，并覆盖 Agent 关闭、整段失败与合法空排序；
- active profile/source snapshot 可回滚且保留历史；
- profile/source discovery/ranking/inbox 可由持久化 kill switch 独立关闭；
- `FI_L4_LEGACY_FALLBACK=1` 保留一个发布周期的全局旧路径。

## 尚未实现

- 任意 API/HTML/MCP/browser connector；
- 分布式 worker、background job 和 durable cross-process execution；
- L5 自主 planner/controller；
- 远程多用户认证和加密 secret store。
