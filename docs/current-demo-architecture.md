# 当前 Runtime 架构

本文描述当前已经实现的 Founder Intelligence 本机运行路径。

## 当前能力

- 一个 FastAPI 服务提供信号控制台、Agent Workbench 和 Settings 页面。
- 一个 Python-native、RSS-only pipeline 同时服务网页刷新和 Agent 工具刷新。
- RSSHub 提供已启用 RSS source 的上游路由；MCP/API/HTML/file 模板尚不可运行。
- 刷新产出 canonical items、append-only JSONL store、signals、Markdown/HTML 对照产物和 refresh status。

## 启动

```bash
docker compose -f config/docker-compose.yml up -d rsshub
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

访问 `http://127.0.0.1:4567/`。应用启动时也会尝试启动 RSSHub；设置 `FI_AUTO_START_RSSHUB=0` 可关闭该行为。

## 刷新入口

网页 `POST /api/refresh` 与 Agent 的 `run_refresh_pipeline` 都调用：

```text
src/agentic-core/agentic_core/pipeline/runner.py
```

完整 pipeline 可单独运行：

```bash
PYTHONPATH=src/agentic-core uv run python -m agentic_core.pipeline.runner --root .
```

Python runner 以固定顺序执行：

```text
fetch_rss
  -> ingest_adapter_output
  -> store_canonical_jsonl
  -> build_signals
  -> publish data/signals/latest.json
```

它使用 `data/app/refresh.lock` 避免并发刷新，失败时保留上一版成功 signals。若个别来源失败但仍有来源成功，状态为 `succeeded_partial`，并在 `data/app/refresh-status.json` 的 `adapter_summary` 中记录脱敏的逐来源状态。

## 模块和数据流

```text
config/sources.yml + config/ingestion-rules.yml
        |
        v
agentic_core.pipeline.fetch_rss
        |
        v
data/adapter-output/rss-fetch-latest.json
        |
        v
agentic_core.pipeline.ingest_adapter_output
        |
        v
data/canonical-items/latest.json
        |
        v
agentic_core.pipeline.store_canonical_jsonl
        |
        +--> data/store/items/YYYY-MM-DD.jsonl
        +--> data/store/runs/YYYY-MM-DD.jsonl
        |
        v
agentic_core.pipeline.build_signals
        |
        +--> data/signals/latest.json
        +--> data/app/tmp/<request-id>/dashboard.md
        +--> data/app/tmp/<request-id>/generated-latest.html
        |
        v
web_workbench.app
```

`src/web/public/` 是当前信号控制台前端；`data/dashboard/index.html` 只是历史对照产物，不是 Web app 首页。

## 运行边界

- `config/sources.yml` 是唯一实际 source registry。
- 当前仅执行 `enabled != false` 且 `source_type == rss` 的来源。
- `schedule.refresh_interval_minutes` 仍只是配置，没有 scheduler 消费。
- `config/user-profile.yml` 和 `config/sources.yml` 可由 Web app 编辑。
- `.env` 保存本机 provider secret 和 `GITHUB_ACCESS_TOKEN`；保存 GitHub token 后会重建 RSSHub 容器。
- Ruby dashboard 和 Ruby refresh scripts 已删除；当前没有第二套 refresh runtime。
