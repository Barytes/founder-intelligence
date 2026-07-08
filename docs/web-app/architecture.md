# 当前 Web App 架构

本文说明当前已经实现的本地 Web app 架构和工作原理。它描述的是 `src/web/` 里的真实运行路径，不是未来重构设想。历史重构计划已归档到 [archive/web-app/refactor-plan.md](../archive/web-app/refactor-plan.md)。

## 总览

当前 Web app 是一个本地常驻控制台。它读取最近一次成功生成的 signals，允许用户从页面触发一次 RSS-only pipeline refresh，并提供两个真实配置编辑入口：

- `config/user-profile.yml`：个性化评分 profile，保存后下一次 refresh 参与后端评分。
- `config/sources.yml`：真实 source registry，保存或启停 RSS source 后下一次 refresh 生效。

```text
Browser
  |
  v
ruby src/web_app.rb
  |
  v
FounderIntelligence::Web::App
  |
  +-- static shell: src/web/public/index.html
  +-- frontend js:  src/web/public/app.js
  +-- data/config:  FounderIntelligence::Web::DataRepository
  +-- refresh:      FounderIntelligence::Web::PipelineRunner
```

Web app 没有重新实现抓取、ingestion、存储或评分逻辑。页面触发 refresh 时，后端仍然串行调用现有 Ruby pipeline 脚本。

## 启动入口

启动命令：

```bash
ruby src/web_app.rb --port 4567
```

默认访问地址：

```text
http://127.0.0.1:4567/
```

`src/web_app.rb` 使用 WEBrick 启动本地 HTTP server。默认绑定 `127.0.0.1`，默认端口是 `4567`，并把所有请求交给 `FounderIntelligence::Web::App#handle`。启动入口会根据 `--host` 和 `--port` 生成写操作允许的本地 origins。

`src/web_app.rb` 只负责 server lifecycle：

- 解析 `--host`、`--port`、`--root`。
- 创建 `FounderIntelligence::Web::App`。
- 把 WEBrick request 转成 app 内部 request。
- 把 app response 写回 WEBrick response。
- 处理 `INT` 和 `TERM` 退出信号。

## 后端路由层

路由集中在 `src/web/app.rb`。

当前路由：

```text
GET   /                    -> src/web/public/index.html
GET   /app.js              -> src/web/public/app.js
GET   /styles.css          -> src/web/public/styles.css
GET   /assets/...          -> src/web/public/assets/...

GET   /api/signals/latest  -> data/signals/latest.json
GET   /api/runs/latest     -> data/store/runs/*.jsonl 的最新记录
GET   /api/refresh/status  -> data/app/refresh-status.json
GET   /api/profile         -> config/user-profile.yml 原文
PUT   /api/profile         -> 校验并写入 config/user-profile.yml
GET   /api/sources         -> config/sources.yml 原文 + UI source rows
PUT   /api/sources         -> 校验并写入 config/sources.yml
POST  /api/sources/:id     -> 启用/停用单个 RSS source
GET   /api/health          -> {"status":"ok"}
POST  /api/refresh         -> 触发一次 pipeline refresh
```

`App` 的职责是很薄的一层 HTTP 编排：

- 返回静态前端 shell 和资源。
- 调用 `DataRepository` 读取本地数据和配置文件。
- 调用 `PipelineRunner` 触发 refresh。
- 对写操作和 `/api/refresh` 做 same-origin 检查，并按启动 host/port 精确匹配 allowed origins。
- 拒绝 `command`、`script`、`path`、`argv`、`args` 这类 refresh 参数，避免把页面 API 变成任意命令执行入口。

## 前端页面

前端资源位于：

```text
src/web/public/
  index.html
  app.js
  styles.css
  assets/brand-logos/
```

`index.html` 是固定应用 shell。它不再加载 `assets/sample-data.js`，也不是把旧 `data/dashboard/index.html` iframe 进来。页面主体包括：

- 顶部 command bar 和统计块。
- 左侧运行栈和来源文件夹。
- 中间 signal 优先队列。
- 右侧 signal 详情。
- `user-profile.yml` 编辑 modal。
- source folder overlay 和 `sources.yml` 编辑器。

`app.js` 启动时读取：

```text
GET /api/signals/latest
GET /api/refresh/status
GET /api/sources
```

然后根据 API 数据渲染统计、筛选器、signal 卡片、详情面板、来源文件夹和运行状态。`user-profile.yml` 只有在用户打开编辑器时才读取：

```text
GET /api/profile
```

前端不再维护第二份 source catalog，也不再把 profile/source 状态保存在浏览器 localStorage。来源列表、启用状态、可运行状态、YAML 原文都来自 `/api/sources`。

## 配置读写层

`src/web/data_repository.rb` 封装 Web app 对本地数据和配置文件的读写。

当前读取规则：

```text
latest_signals
  -> 读取 data/signals/latest.json
  -> 文件不存在时返回 status=empty
  -> JSON 损坏时返回 status=error

latest_run
  -> 读取 data/store/runs/*.jsonl 中排序最后的文件
  -> 取最后一条非空 JSONL 记录
  -> 没有 run 时返回 status=empty
  -> JSON 损坏时返回 status=error

refresh_status
  -> 读取 data/app/refresh-status.json
  -> 文件不存在时返回 status=idle
  -> JSON 损坏时返回 status=error

profile
  -> 读取 config/user-profile.yml 原文

sources
  -> 读取 config/sources.yml 原文
  -> 从 sources 和 source_templates 派生 UI rows
```

当前写入规则：

- `PUT /api/profile` 要求 body 中的 `content` 是合法 YAML mapping，包含 `version`、`user.name`，并且至少有一个可用于匹配的 interest、watch entity 或 goal keyword。
- `PUT /api/sources` 要求 body 中的 `content` 是合法 YAML mapping，包含 `version` 和 `sources` 数组；每个真实 RSS source 必须有唯一 `id`、`name`、`provider`、`category`、布尔 `enabled` 和 HTTP(S) `connection.rss_url`。
- `POST /api/sources/:id` 只允许切换 `source_type: rss` 的真实 source，不允许启用 source template 或未实现 source type。`App#handle` 内部保留 `PATCH` 兼容，但真实 WEBrick 浏览器路径使用 `POST`。
- 写文件使用临时文件再 `mv` 覆盖目标文件。

## Refresh Runner

`src/web/pipeline_runner.rb` 负责把页面上的“刷新”转换成一次串行 pipeline 执行。

当前步骤顺序：

```text
fetch_rss
  -> ingest_adapter_output
  -> store_canonical_jsonl
  -> build_signals
  -> publish data/signals/latest.json
```

对应命令由 `PipelineRunner#default_commands` 构造：

```text
ruby src/fetch_rss.rb --output data/adapter-output/rss-fetch-latest.json

ruby src/ingest_adapter_output.rb \
  --input data/adapter-output/rss-fetch-latest.json \
  --output data/canonical-items/latest.json

ruby src/store_canonical_jsonl.rb \
  --input data/canonical-items/latest.json \
  --store-dir data/store

ruby src/build_signals.rb \
  --input data/canonical-items/latest.json \
  --profile config/user-profile.yml \
  --rules config/signal-rules.yml \
  --output data/app/tmp/<request_id>/signals.json \
  --markdown data/app/tmp/<request_id>/dashboard.md \
  --html data/app/tmp/<request_id>/generated-latest.html
```

runner 的运行机制：

1. 创建 `data/app/`。
2. 通过 `data/app/refresh.lock` 防止并发 refresh。
3. 生成 `refresh-<timestamp>-<random>` 格式的 `request_id`。
4. 写入 `data/app/refresh-status.json`，状态为 `running`。
5. 使用 `Open3.capture3` 在 repo root 下按固定顺序运行每一步。
6. 每一步记录 exit status、开始和结束时间、stdout/stderr 尾部日志。
7. 每一步后验证关键产物是否存在且 JSON 可解析。
8. 从 store step stdout 提取本次输入、新增、重复数量。
9. 在发布前对比上一版和新版 signal id，生成 `signal_diff`。
10. `build_signals` 产物通过验收后，先复制到临时发布文件，再 `mv` 到 `data/signals/latest.json`。
11. 成功时写入 `succeeded` 或 `succeeded_empty`。
12. 失败时写入 `failed`，并保留原有 `data/signals/latest.json`。
13. 成功后清理 `data/app/tmp/`，默认保留最近 5 次 refresh 目录。

每个命令有 timeout，默认 `120` 秒。runner 会对包含 token 或 authorization 的输出做简单脱敏，并只保存尾部日志。

## 运行状态文件

Web app 引入的运行状态位于：

```text
data/app/
  refresh-status.json
  refresh.lock
  tmp/<request_id>/
```

这些是本地运行产物，不是源代码或配置。

`refresh-status.json` 是页面展示 refresh 状态的主要来源，常见状态包括：

```text
idle
running
succeeded
succeeded_empty
failed
failed_stale_lock
```

成功状态里还会包含：

- `started_at`、`finished_at`、`duration_seconds`。
- `store_summary`：本次处理、新增、重复、丢弃数量。
- `signal_diff`：本次推荐队列是否相对上一版变化。
- `last_successful_generated_at` 和 `last_successful_input_run_id`。

`refresh.lock` 用于防止同一时间启动多个 refresh。如果 lock 中的 pid 不存在，runner 会把状态标记为 `failed_stale_lock` 并释放 lock。

## 当前边界

当前实现边界必须按真实代码理解：

- 实现的 fetch path 只有 RSS。
- `config/user-profile.yml` 和 `config/sources.yml` 已经可以从 Web app 写入；其他 `config/` 文件仍不提供页面编辑入口。
- MCP、API、HTML、file source template 可以展示为未来扩展，但当前不能启用为可运行 fetcher。
- refresh 是用户点击触发，不是 scheduler 触发。
- refresh 当前仍是同步 HTTP 请求；页面会等待整个 pipeline 完成。
- Web app 读取 `data/signals/latest.json` 展示最新成功结果，不读取旧静态 sample data。
- `src/build_signals.rb` 仍可生成 Markdown/HTML 对照产物，但 Web app 首页来自 `src/web/public/index.html`。

## 测试覆盖

当前 Web app 相关测试在：

```text
tests/test_web_app.rb
tests/test_web_core.rb
```

测试覆盖的重点包括：

- 首页是 Web app shell，不依赖 `assets/sample-data.js`。
- `app.js` 使用 `/api/signals/latest`、`/api/profile`、`/api/sources`，不使用旧 `window.FI_*` sample globals。
- brand logo assets 可从 `src/web/public/assets/` 服务。
- `/api/signals/latest` 返回成功 signal output。
- `/api/profile` 可读写 `config/user-profile.yml`，并拒绝 invalid YAML 或缺少核心画像字段的 profile。
- `/api/sources` 可读写 `config/sources.yml`，并拒绝不符合 RSS-only MVP 运行边界的 sources YAML。
- `/api/sources/:id` 可启用/停用真实 RSS source，并拒绝不存在的 source。
- `/api/refresh` 拒绝 cross-origin 请求。
- `/api/refresh` 拒绝命令参数。
- `DataRepository` 区分 empty、valid 和 corrupt JSON。
- `PipelineRunner` 成功 refresh 后发布 `data/signals/latest.json`。
- refresh 失败不覆盖旧的成功 signals。
- lock 存在且进程仍存活时拒绝并发 refresh。

## 文件分工

```text
src/web_app.rb
  本地 WEBrick 启动入口。

src/web/app.rb
  HTTP route、静态资源、API response、配置写入 guard 和 refresh request guard。

src/web/data_repository.rb
  读取 latest signals、latest run、refresh status、profile 和 sources，并写入允许编辑的配置文件。

src/web/pipeline_runner.rb
  串行调用现有 RSS-only pipeline，管理 lock、status、临时产物、diff 和发布。

src/web/public/index.html
  固定 Web app shell。

src/web/public/app.js
  浏览器端 API 读取、signal 渲染、来源 overlay、profile/source YAML 编辑和 refresh 交互。

src/web/public/styles.css
  控制台视觉样式和响应式布局。
```
