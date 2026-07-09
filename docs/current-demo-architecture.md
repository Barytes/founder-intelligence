# 当前 Runtime 架构与工作流程

本文描述 Founder Intelligence 当前真实运行边界：底层是本地确定性 RSS-only 信息聚合 pipeline，上层是一个 FastAPI 本地 Web app 控制台。Web app 不重写抓取、ingestion、存储或评分逻辑；它负责展示最新成功 signals、编辑允许暴露的配置，并触发一次同步 refresh。

更细的 Web app 路由、前端和 runner 说明见 [web-app/architecture.md](web-app/architecture.md)。

## 当前功能

当前 demo 的目标是把多个 RSSHub 信息源抓取下来，转换成统一结构，做本地存储，再根据用户画像和规则生成每日情报看板。

它已经具备：

- 从 RSSHub 抓取 RSS/Atom 信息源
- 将原始条目转换为 canonical item
- 清理 HTML、标准化链接和时间
- 生成内容 hash 和去重 key
- 对条目打质量标记
- 将 canonical item 追加写入 JSONL
- 根据用户画像和规则计算重要性、相关性和总分
- 生成 `data/signals/latest.json`
- 生成 `data/dashboard/latest.md`
- 生成 `data/dashboard/latest.html`
- 生成辅助信息源看板 `data/dashboard/source-dashboard.html`

它暂时不包含：

- 常驻调度器
- 数据库
- 远程多人 Chat UI
- 自动 LLM 总结
- 无边界 Agentic planning
- 自动行动执行
- 长期记忆
- 可运行的 MCP/API/HTML fetcher
当前实现已经具备：

- 从 RSSHub 抓取启用的 RSS/Atom 信息源。
- 将原始条目转换成 canonical item。
- 清理 HTML、标准化链接和时间。
- 生成内容 hash 和去重 key。
- 对条目打质量标记。
- 将 canonical item 追加写入 JSONL store。
- 根据 `config/user-profile.yml` 和 `config/signal-rules.yml` 计算重要性、相关性和总分。
- 生成 `data/signals/latest.json` 和 `data/dashboard/latest.md`。
- 通过 `web_workbench.app` 启动统一 FastAPI 本地 Web app，读取最新成功 signals。
- 在同一 HTTP 服务下通过 `/agent` 提供 Agentic Core 工作台。
- Web app 可编辑 `config/user-profile.yml` 和 `config/sources.yml`。
- Web app 可手动触发一次 RSS-only refresh，refresh 暂时仍调用现有 Ruby scripts。

当前实现不包含：

- 自动调度器。
- 数据库。
- Chat UI。
- LLM 总结。
- Agentic planning。
- 自动行动执行。
- 长期记忆。
- 可运行的 MCP/API/HTML/file fetcher。

## 目录结构

当前主要目录是：

```text
config/        YAML 配置和 Docker Compose 配置
src/           Ruby pipeline 源代码和 Web app 源代码
data/          抓取结果、canonical items、signals、dashboard、JSONL store 和运行状态
docs/          项目文档
tests/         Web app 和 pipeline runner 测试
```

`config/` 是配置层，`src/` 是执行层，`data/` 是运行产物层。Web app 的前端资源位于 `src/web/public/`，不是 `data/dashboard/index.html`。

## CLI Pipeline 入口

完整 CLI pipeline 从项目根目录运行：

```bash
docker compose -f config/docker-compose.yml up -d rsshub
ruby src/fetch_rss.rb --output data/adapter-output/rss-fetch-latest.json
ruby src/ingest_adapter_output.rb --input data/adapter-output/rss-fetch-latest.json --output data/canonical-items/latest.json
ruby src/store_canonical_jsonl.rb --input data/canonical-items/latest.json --store-dir data/store
ruby src/build_signals.rb --input data/canonical-items/latest.json --profile config/user-profile.yml --rules config/signal-rules.yml
```

`src/build_signals.rb` 默认输出：

```text
data/signals/latest.json
data/dashboard/latest.md
data/dashboard/generated-latest.html
```

其中 `generated-latest.html` 是过渡期静态 HTML 产物，不是当前 Web app 首页。

## Web App 入口

启动命令：

```bash
FI_AUTO_START_RSSHUB=1 PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

访问地址：

```text
http://127.0.0.1:4567/
```

Web app 默认绑定 `127.0.0.1`。页面读取 `data/signals/latest.json` 展示最新成功 signals；点击刷新时由 `src/agentic-core/web_workbench/pipeline_runner.py` 顺序调用 Ruby CLI pipeline。设置 `FI_AUTO_START_RSSHUB=1` 时，FastAPI startup 会先尝试运行 `docker compose -f config/docker-compose.yml up -d rsshub`。

## 架构分层

当前 runtime 可以理解为六层。

第一层是 RSSHub。

`config/docker-compose.yml` 启动本地 RSSHub，默认服务地址是：

```text
http://localhost:1200
```

第二层是 source 配置。

`config/sources.yml` 是当前唯一 source registry。当前可运行 source 必须满足：

```ruby
source["enabled"] != false && source["source_type"] == "rss"
```

MCP/API/HTML/file source template 可以存在于配置中，但不能被当前 fetcher 执行。

第三层是 fetch adapter。

`src/fetch_rss.rb` 读取 `config/sources.yml` 和 `config/ingestion-rules.yml`，筛选启用的 RSS source，请求每个 source 的 `connection.rss_url`，解析 RSS/Atom XML，然后输出 adapter result：

```text
data/adapter-output/rss-fetch-latest.json
```

第四层是 ingestion。

`src/ingest_adapter_output.rb` 读取 adapter output、`config/sources.yml`、`config/ingestion-rules.yml`，把 raw item 变成统一 canonical item：

```text
data/canonical-items/latest.json
```

第五层是 storage。

`src/store_canonical_jsonl.rb` 将新 item 追加写入：

```text
data/store/items/YYYY-MM-DD.jsonl
data/store/runs/YYYY-MM-DD.jsonl
```

它是 append-only 文件存储，不是数据库。

第六层是 signal processing、Web app 和 Agent Workbench。

`src/build_signals.rb` 生成 signal JSON 和 Markdown。`src/agentic-core/web_workbench/app.py` 负责提供本地 FastAPI Web app 和 `/agent` 工作台，`src/agentic-core/web_workbench/pipeline_runner.py` 负责把页面 refresh 转换成一次固定顺序的 Ruby pipeline 执行。

## 数据流

完整数据流如下：

```text
config/sources.yml
config/ingestion-rules.yml
        |
        v
src/fetch_rss.rb
        |
        v
data/adapter-output/rss-fetch-latest.json
        |
        v
src/ingest_adapter_output.rb
        |
        v
data/canonical-items/latest.json
        |
        v
src/store_canonical_jsonl.rb
        |
        v
data/store/items/YYYY-MM-DD.jsonl
data/store/runs/YYYY-MM-DD.jsonl
        |
        v
src/build_signals.rb
        |
        v
data/signals/latest.json
data/dashboard/latest.md
        |
        v
src/agentic-core/web_workbench/app.py
```

然后生成：

```text
data/dashboard/source-dashboard.html
```
## 当前边界

- 当前抓取路径只有 RSS。
- `schedule.refresh_interval_minutes` 仍只是配置字段，没有调度器消费。
- `config/user-profile.yml` 和 `config/sources.yml` 可从 Web app 编辑；其他 `config/` 文件仍需手动编辑。
- 当前 HTTP 后端是 Python/FastAPI；迁移前 Ruby Web app 后端已移除。
- Ruby scripts 仍是 refresh pipeline 的业务执行器。
- Web app 的 source 启用/停用会写回 `config/sources.yml`。
- Web app refresh 当前是同步 HTTP 请求，长任务期间页面会等待请求返回。
- `data/dashboard/index.html` 是历史静态模板/对照文件，不是当前 Web app 首页。
- `src/build_source_dashboard.rb` 仍是可手动运行的旧式信息源检查 helper，不属于当前主 Web app 路径。
