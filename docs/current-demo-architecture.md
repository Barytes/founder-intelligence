# 当前 Demo 功能、架构与工作流程

本文描述当前 Founder Intelligence demo 的真实实现边界。它不是一个常驻 Web 应用，也不是 Agentic AI 应用，而是一个本地运行的确定性信息聚合流水线。

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
- 生成辅助信息源看板 `design-demos/information-source-dashboard.html`

它暂时不包含：

- 常驻调度器
- 数据库
- Chat UI
- LLM 总结
- Agentic planning
- 自动行动执行
- 长期记忆
- 可运行的 MCP/API/HTML fetcher

## 目录结构

当前主要目录是：

```text
config/        YAML 配置、Docker Compose 配置、fetcher contract
src/           Ruby 源代码
data/          抓取结果、canonical items、signals、dashboard、JSONL store
docs/          项目文档
design-demos/ 设计看板和截图
```

`config/` 是静态配置层，`src/` 是执行层，`data/` 是运行产物层。

## 运行入口

完整 demo 流程从项目根目录运行：

```bash
docker compose -f config/docker-compose.yml up -d rsshub
ruby src/fetch_rss.rb --output data/adapter-output/rss-fetch-latest.json
ruby src/ingest_adapter_output.rb --input data/adapter-output/rss-fetch-latest.json --output data/canonical-items/latest.json
ruby src/store_canonical_jsonl.rb --input data/canonical-items/latest.json --store-dir data/store
ruby src/build_signals.rb --input data/canonical-items/latest.json --profile config/user-profile.yml --rules config/signal-rules.yml
```

如果只想查看已有结果，可以直接打开：

```text
data/dashboard/latest.html
```

## 架构分层

当前 demo 可以理解为五层。

第一层是 RSSHub。

`config/docker-compose.yml` 启动本地 RSSHub，服务地址是：

```text
http://localhost:1200
```

`config/sources.yml` 中的 RSS 源都指向这个本地 RSSHub。

第二层是 fetch adapter。

`src/fetch_rss.rb` 读取 `config/sources.yml` 和 `config/ingestion-rules.yml`，筛选启用的 RSS 源，请求每个 source 的 `connection.rss_url`，解析 RSS/Atom XML，然后输出 adapter result。

输出位置通常是：

```text
data/adapter-output/rss-fetch-latest.json
```

第三层是 ingestion。

`src/ingest_adapter_output.rb` 读取 adapter output、`config/sources.yml`、`config/ingestion-rules.yml`，把 raw item 变成统一的 canonical item。

输出位置是：

```text
data/canonical-items/latest.json
```

第四层是 storage。

`src/store_canonical_jsonl.rb` 读取 canonical items，将新 item 追加写入：

```text
data/store/items/YYYY-MM-DD.jsonl
data/store/runs/YYYY-MM-DD.jsonl
```

它是 append-only 文件存储，不是数据库。

第五层是 signal processing 和 dashboard。

`src/build_signals.rb` 读取 canonical items、`config/user-profile.yml`、`config/signal-rules.yml`，生成用户相关的 intelligence signals，并输出 JSON、Markdown、HTML dashboard。

## 工作流程

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
data/dashboard/latest.html
```

## 当前实现边界

当前真正实现的抓取路径只有 RSS。

`config/sources.yml` 里可以出现 `mcp`、`api`、`html` 的模板或未来设计，但 `src/fetch_rss.rb` 只筛选：

```ruby
source["enabled"] != false && source["source_type"] == "rss"
```

因此 MCP/API/HTML 信息源目前不会被抓取。

当前配置里也有 `schedule.refresh_interval_minutes`，但没有调度器消费这个字段。也就是说，当前 demo 是手动运行脚本，不会自动定时抓取。

## 辅助信息源看板

`src/build_source_dashboard.rb` 不是主情报流水线的一部分，但可以帮助检查信息源状态。

它读取：

```text
config/sources.yml
data/adapter-output/rss-fetch-latest.json
data/canonical-items/latest.json
```

然后生成：

```text
design-demos/information-source-dashboard.html
```

这个页面适合用来检查哪些源启用、哪些源抓取成功、raw item 数量、canonical item 数量和错误状态。
