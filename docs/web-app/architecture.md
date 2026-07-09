# 当前 Web App 架构

本文说明当前已经实现的本地 Web app 架构和工作原理。它描述的是 `web_workbench.app` 统一 FastAPI 后端、`src/web/public/` dashboard 前端和 `src/agentic-core/web_workbench/static/` Agent/Settings 前端的真实运行路径，不是未来重构设想。历史重构计划已归档到 [archive/web-app/refactor-plan.md](../archive/web-app/refactor-plan.md)。

## 总览

当前 Web app 是一个本地常驻控制台，HTTP 后端已经统一到 Python/FastAPI。它读取最近一次成功生成的 signals，允许用户从页面触发一次 RSS-only pipeline refresh，并提供 dashboard 配置入口和本机 Agent 设置入口。

Dashboard 配置入口：

- `config/user-profile.yml`：个性化评分 profile，保存后下一次 refresh 参与后端评分。
- `config/sources.yml`：真实 source registry，保存或启停 RSS source 后下一次 refresh 生效。

Agent/settings 配置入口：

- `.env`：provider API keys 和 `GITHUB_ACCESS_TOKEN`，页面/API 只显示脱敏状态。
- `config/agentic-core.local.yml`：gitignored 本机 provider profile、model 和 base URL 覆盖。

```text
Browser
  |
  v
uvicorn web_workbench.app:app
  |
  v
FastAPI unified backend
  |
  +-- static shell: src/web/public/index.html
  +-- frontend js:  src/web/public/app.js
  +-- agent shell:  src/agentic-core/web_workbench/static/index.html
  +-- settings UI:  src/agentic-core/web_workbench/static/settings.html
  +-- data/config:  web_workbench.dashboard_repository.DashboardRepository
  +-- refresh:      web_workbench.pipeline_runner.PipelineRunner
  +-- agent core:   agentic_core.AgenticCore
```

Web app 没有重新实现抓取、ingestion、存储或评分逻辑。页面触发 refresh 时，Python 后端仍然串行调用现有 Ruby pipeline 脚本。

## 启动入口

启动命令：

```bash
FI_AUTO_START_RSSHUB=1 PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

默认访问地址：

```text
http://127.0.0.1:4567/
```

`web_workbench.app` 使用 FastAPI 提供唯一 HTTP 服务。默认本机绑定由 Uvicorn 命令控制；same-origin guard 会接受请求实际 host/port 对应的 Origin，并保留 `FI_ALLOWED_ORIGINS` 覆盖项。`FI_AUTO_START_RSSHUB=1` 会在 app startup 时尝试启动 `config/docker-compose.yml` 中的 `rsshub` 服务；Docker 不可用时不会阻止 Web app 启动。

## 后端路由层

路由集中在 `src/agentic-core/web_workbench/app.py`。

当前路由：

```text
GET   /                    -> src/web/public/index.html
GET   /app.js              -> src/web/public/app.js
GET   /styles.css          -> src/web/public/styles.css
GET   /assets/...          -> src/web/public/assets/...
GET   /agent               -> src/agentic-core/web_workbench/static/index.html
GET   /settings            -> src/agentic-core/web_workbench/static/settings.html
GET   /agent/static/...    -> src/agentic-core/web_workbench/static/...

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

GET   /api/agent/default-config     -> Agent provider/config 摘要
POST  /api/agent/provider-settings  -> 保存 Agent provider 配置
POST  /api/agent/chat               -> 调用 Agentic Core
GET   /api/settings/env             -> .env secret 脱敏状态
PUT   /api/settings/env             -> 保存 GITHUB_ACCESS_TOKEN 到 .env
```

FastAPI app 的职责是很薄的一层 HTTP 编排：

- 返回静态前端 shell 和资源。
- 调用 `DashboardRepository` 读取本地数据和配置文件。
- 调用 Python `PipelineRunner` 触发 refresh；runner 内部调用 Ruby scripts。
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

Agent 和配置页资源位于：

```text
src/agentic-core/web_workbench/static/
  index.html
  app.js
  settings.html
  settings.js
  styles.css
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

`/agent` 只保留聊天、工具状态和工具调用日志。Agent provider、model、base URL、API key 迁移到 `/settings`。`/settings` 还可以写入 `GITHUB_ACCESS_TOKEN` 到项目根目录 `.env`，用于 RSSHub GitHub route 等本机依赖；页面和 API 只显示脱敏状态，不回传 secret 明文。

## 配置读写层

`src/agentic-core/web_workbench/dashboard_repository.py` 封装 Web app 对本地数据和配置文件的读写。

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
- `POST /api/sources/:id` 只允许切换 `source_type: rss` 的真实 source，不允许启用 source template 或未实现 source type。FastAPI 后端保留 `PATCH` 兼容，但浏览器运行路径使用 `POST`。
- `POST /api/agent/provider-settings` 写入 provider secret 到 `.env`，并把 model/base URL/active saved profile 写入 gitignored `config/agentic-core.local.yml`。`Saved Configuration` 只包含 local config 中用户实际保存过的 profile；OpenAI、DeepSeek、OpenRouter、Custom 只作为 `Provider Type` 模板展示。
- `PUT /api/settings/env` 只写入 `GITHUB_ACCESS_TOKEN` 到 `.env`，响应只返回配置状态和脱敏 preview。
- `DashboardRepository` 写 profile/sources 时使用临时文件再 `mv` 覆盖目标文件。当前 provider/local settings 写入仍是直接改写 `.env` 或 `config/agentic-core.local.yml`，属于本机开发便利实现，不是生产级 secret/config storage。

## Refresh Runner

`src/agentic-core/web_workbench/pipeline_runner.py` 负责把页面上的“刷新”转换成一次串行 pipeline 执行。

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
5. 使用 `subprocess.run` 在 repo root 下按固定顺序运行每一步。
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
- `config/user-profile.yml` 和 `config/sources.yml` 已经可以从 Web app 写入。
- `.env` 和 gitignored `config/agentic-core.local.yml` 可从 `/settings` 写入；已提交的其他 `config/` 文件仍不提供页面编辑入口。
- MCP、API、HTML、file source template 可以展示为未来扩展，但当前不能启用为可运行 fetcher。
- refresh 是用户点击触发，不是 scheduler 触发。
- refresh 当前仍是同步 HTTP 请求；页面会等待整个 pipeline 完成。
- Web app 读取 `data/signals/latest.json` 展示最新成功结果，不读取旧静态 sample data。
- `src/build_signals.rb` 仍可生成 Markdown/HTML 对照产物，但 Web app 首页来自 `src/web/public/index.html`。

## 测试覆盖

当前 Web app 相关测试在：

```text
tests/test_unified_web_app.py
tests/test_python_pipeline_runner.py
tests/test_workbench_api.py
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
- `/api/agent/provider-settings` 和 `/api/settings/env` 拒绝 cross-origin 写入，且不在响应中泄露 secret。
- `Saved Configuration` 不展示内置 provider templates，只展示 local config 中已保存的 profile。
- `DataRepository` 区分 empty、valid 和 corrupt JSON。
- `PipelineRunner` 成功 refresh 后发布 `data/signals/latest.json`。
- refresh 失败不覆盖旧的成功 signals。
- lock 存在且进程仍存活时拒绝并发 refresh。

## 文件分工

```text
src/agentic-core/web_workbench/app.py
  当前统一 FastAPI HTTP 入口，服务 dashboard、agent workbench、settings 页面、dashboard API 和 agent/settings API。

src/agentic-core/web_workbench/dashboard_repository.py
  读取 latest signals、latest run、refresh status、profile 和 sources，并写入允许编辑的配置文件。

src/agentic-core/web_workbench/pipeline_runner.py
  串行调用现有 Ruby RSS-only pipeline scripts，管理 lock、status、临时产物、diff 和发布。

src/web/public/
  Dashboard 前端静态资源。迁移前 Ruby Web app 后端文件已移除，只保留前端 shell。

src/web/public/index.html
  固定 Web app shell。

src/web/public/app.js
  浏览器端 API 读取、signal 渲染、来源 overlay、profile/source YAML 编辑和 refresh 交互。

src/web/public/styles.css
  控制台视觉样式和响应式布局。

src/agentic-core/web_workbench/static/
  Agent Workbench 和 Settings 前端静态资源。
```
