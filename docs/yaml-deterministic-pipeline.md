# 基于 YAML 配置驱动的确定性流水线

本文说明当前 demo 中每个 YAML 文件的作用，以及它们在代码流程里如何被消费。

## 总体判断

当前项目是一个配置驱动的确定性流水线：

```text
YAML 配置
-> RSS 抓取
-> canonical ingestion
-> JSONL 存储
-> 规则打分
-> dashboard 输出
```

这里的 YAML 不是装饰，而是把信息源、清洗规则、用户画像和评分逻辑从 Ruby 代码中拆出来。这样做的好处是：代码负责执行，YAML 负责策略和边界。

但需要区分两类 YAML：

- 运行时真正被代码读取的配置
- 当前作为设计契约或历史备用存在的 YAML

## 当前 YAML 文件

所有 YAML 文件都集中在 `config/` 目录。

```text
config/docker-compose.yml
config/sources.yml
config/ingestion-rules.yml
config/signal-rules.yml
config/user-profile.yml
config/fetcher-contract.yml
config/rss-sources.yml
```

其中，主 demo 流程实际读取的是：

```text
config/sources.yml
config/ingestion-rules.yml
config/signal-rules.yml
config/user-profile.yml
```

`config/docker-compose.yml` 被 Docker Compose 使用，不被 Ruby 读取。

`config/fetcher-contract.yml` 是 fetcher adapter 的设计契约，当前不被 Ruby 主流程读取。

`config/rss-sources.yml` 是旧版或简化版 RSS 源配置，当前不被主流程读取。

## `config/docker-compose.yml`

这个文件负责启动本地 RSSHub。

它定义的服务是：

```text
rsshub
```

端口映射是：

```text
1200:1200
```

因此当前 RSSHub 地址是：

```text
http://localhost:1200
```

因为 Compose 文件位于 `config/` 目录，它通过 `env_file: ../.env` 读取项目根目录的 `.env`，并把其中的 `GITHUB_ACCESS_TOKEN` 传给 RSSHub。GitHub Trending 源通常依赖这个 token。

启动命令是：

```bash
docker compose -f config/docker-compose.yml up -d rsshub
```

## `config/sources.yml`

这个文件是信息源注册表，决定系统“从哪里抓”。

每个 source 会声明：

- `id`
- `name`
- `source_type`
- `provider`
- `fetcher`
- `enabled`
- `priority`
- `category`
- `connection`
- `schedule`
- `tags`
- `notes`

当前主抓取脚本 `src/fetch_rss.rb` 会读取它，并筛选：

```ruby
source["enabled"] != false && source["source_type"] == "rss"
```

所以当前只有启用的 RSS 源会被抓。

`connection.rss_url` 是真正请求的地址。`connection.rsshub_route` 是给人看的 RSSHub route 辅助信息。

`priority`、`category`、`tags` 在抓取阶段不影响请求，但会在 ingestion 阶段被写入 canonical item，后续又会影响 signal scoring 和 dashboard 展示。

当前文件里还有 `source_templates`，例如小红书 MCP、微信公众号 MCP。这些是未来扩展模板，不会被当前主流程自动抓取。

## `config/ingestion-rules.yml`

这个文件同时参与 fetch 阶段和 ingestion 阶段。

在 `src/fetch_rss.rb` 中，它实际使用：

- `fetch.user_agent`
- `fetch.timeout_seconds`
- `fetch.max_items_per_source`

这些字段控制 HTTP 请求的 User-Agent、超时时间和每个 source 的最大 item 数。

在 `src/ingest_adapter_output.rb` 中，它控制 canonical item 的生成规则。

`normalization` 控制：

- 是否清理 HTML
- 是否折叠空白
- summary 最大长度
- content 最大长度
- 去除哪些 tracking query params
- 是否保留 raw payload

`deduplication` 控制：

- content hash 使用哪些字段
- 全局去重策略
- 不同 provider 的去重优先级

例如 RSS/GitHub 源会优先用 `guid`、`normalized_link` 等字段构造 `dedupe_key`。

`canonical_item.required_fields` 控制 canonical item 必填字段。缺少必填字段的 item 会被丢弃。

`quality_gates` 控制质量标记和丢弃规则。例如：

- 标题为空时丢弃
- content 为空时打 `content_empty`
- published_at 为空时打 `published_at_empty`
- author 为空时打 `author_empty`

需要注意：`field_mappings` 当前更像未来通用 mapper 的设计说明。当前 RSS fetcher 已经把 raw item 输出为固定字段，所以 ingestion 代码直接读取 `raw_item["title"]`、`raw_item["link"]` 等字段。

## `config/user-profile.yml`

这个文件描述用户画像，决定“什么信息跟用户有关”。

`src/build_signals.rb` 会读取它，并使用：

- `goals[].title`
- `goals[].keywords`
- `interests`
- `watch_entities`
- `negative_preferences`
- `output_preferences.default_top_n`

代码会把 goals、interests、watch entities 合并成 profile terms，然后在 item 的 `title + summary + content` 中做字符串匹配。

命中用户画像关键词会提高相关性分数。

命中 `negative_preferences` 会降低相关性分数，并在风险提示中标出。

当前 `risk_preferences`、`output_preferences.language`、`output_preferences.tone`、`output_preferences.card_fields` 主要是产品配置雏形，还没有完整驱动输出模板。

## `config/signal-rules.yml`

这个文件决定“哪些内容算信号、如何打分、如何过滤、输出什么追问和风险”。

`keyword_rules` 定义主题词，例如：

- AI Agent
- AI Coding
- Context
- MCP
- Meeting Intelligence
- Investment Research
- Social Signal
- Open Source

`src/build_signals.rb` 会用这些词匹配 canonical item 的文本。命中后会生成主题标签，并参与重要性和相关性评分。

`scoring` 定义权重：

- `priority_weights`：source 优先级权重
- `source_type_weights`：source 类型权重
- `recency`：时效性权重
- `clamp`：分数上下限

重要性分数主要来自：

- source priority
- source type
- recency
- source tags 是否存在
- keyword rule 命中数量
- 内容长度是否足够

相关性分数主要来自：

- keyword rule 命中数量
- user profile term 命中数量
- source tag 与用户画像是否相近
- negative preference 惩罚

最终总分是：

```ruby
importance_score * 0.45 + relevance_score * 0.55
```

`recommendation` 控制：

- 输出多少条 signal
- 最低相关性门槛
- summary 句子数
- 推荐问题数量
- 风险提示数量

`filters` 控制排除哪些 source 或 category。当前 `reference_feed` 会被排除。

`question_templates` 和 `risk_templates` 会写入 dashboard 中的“建议追问”和“风险/反例”。

## `config/fetcher-contract.yml`

这个文件当前是设计契约，不是运行时配置。

它定义未来统一 fetcher adapter 应该满足的接口：

```text
input: source + context
output: source_id/source_type/provider/fetched_at/status/items/errors
```

它还描述了 RSS、MCP、API、HTML fetcher 的预期输入、错误类型和输出结构。

当前代码没有读取这个文件。它的价值在于后续可以升级成 schema validation 或测试 fixture，要求所有 fetcher 输出都满足同一 contract。

## `config/rss-sources.yml`

这个文件是旧版或简化版 RSS source 配置。

当前没有 Ruby 脚本读取它。主 source registry 是 `config/sources.yml`。

后续如果不再需要，可以删除；如果保留，应明确标记为 legacy example。

## 代码流程中的 YAML 运作

完整流程如下：

```text
config/docker-compose.yml
        |
        v
启动本地 RSSHub

config/sources.yml
config/ingestion-rules.yml
        |
        v
src/fetch_rss.rb
        |
        v
data/adapter-output/rss-fetch-latest.json

config/sources.yml
config/ingestion-rules.yml
        |
        v
src/ingest_adapter_output.rb
        |
        v
data/canonical-items/latest.json

data/canonical-items/latest.json
        |
        v
src/store_canonical_jsonl.rb
        |
        v
data/store/items/YYYY-MM-DD.jsonl
data/store/runs/YYYY-MM-DD.jsonl

config/user-profile.yml
config/signal-rules.yml
data/canonical-items/latest.json
        |
        v
src/build_signals.rb
        |
        v
data/signals/latest.json
data/dashboard/latest.md
data/dashboard/latest.html
```

`src/store_canonical_jsonl.rb` 不读取 YAML。它只读取 canonical JSON，并追加写入 JSONL。

## 对未来 Agentic AI 版本的边界

如果后续把项目改成 Agentic AI 应用，YAML 仍然适合保留，但应该只作为稳定控制面。

适合继续放在 YAML 中的内容：

- source registry
- deterministic ingestion rules
- scoring defaults
- user preference seed data
- adapter contracts
- policy knobs

不适合放在 YAML 中的内容：

- per-run agent reasoning
- evidence gathered during research
- task queue
- user feedback history
- long-term memory
- trace/replay records
- changing project state
- agent decisions

目标分层应该是：

```text
YAML/static contracts
+ deterministic ingestion
+ runtime evidence/state store
+ agent research and planning layer
+ trace/review/writeback gates
```

也就是说，YAML 定义边界和默认规则；runtime store 记录证据、状态、决策和 trace；agent 在这些可靠产物之上做研究、判断和追问。

不要让 agent 在普通运行中静默改写 YAML。新增 source、修改 priority、修改 scoring rule、改用户画像，都应该走 review-gated writeback。
