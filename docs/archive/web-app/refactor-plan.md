# 常驻 Web 应用架构

本文描述 Founder Intelligence 从一次性静态 HTML 看板升级为常驻本地 Web 应用时的需求、功能边界、架构和实现约束。它用于指导后续实现，也用于帮助维护者理解当前 demo 与目标 Web 应用之间的关系。

## 背景

当前项目是一个本地运行的确定性信息聚合流水线：

```text
RSS 抓取
-> canonical ingestion
-> JSONL 存储
-> 规则评分
-> data/dashboard/index.html
```

`data/dashboard/index.html` 当前是由 `design-demos/index.html` 迁移而来的控制台模板。它适合验证未来 Web app 的首屏信息架构、来源管理和 signal 详情交互，但不适合承担长期使用中的应用状态。

目标 Web 应用不是把 HTML 文件自动改写得更频繁，而是把页面变成一个常驻读取数据的应用界面。数据更新仍然来自抓取、清理、评分流水线，但页面本身不再是流水线的最终静态产物。

## 目标

常驻 Web 应用需要满足以下目标：

- 页面作为稳定入口存在，不随每次抓取重新生成。
- 每次数据更新后，页面能读取并展示最新 intelligence signals。
- 页面以当前 `data/dashboard/index.html` 控制台模板为视觉和交互合同，只改变数据装载方式。
- 保留当前 RSS-only 抓取边界，不因为 Web 应用引入未实现的 MCP/API/HTML fetcher。
- 保留当前确定性评分逻辑，避免在第一版中引入 LLM 总结、chat UI 或 agentic planning。
- 保留本地优先的开发体验，适合在个人机器上运行、调试和迭代。
- 让数据层、评分层、Web 展示层分离，便于后续替换存储或扩展前端。

## 非目标

第一版常驻 Web 应用不包含：

- 多用户账号、登录和权限系统。
- 云端部署和公网访问。
- 可编辑 `config/` 的管理后台。
- 非 RSS source 的真实抓取能力。
- LLM 摘要、问答、行动建议或自动 agent workflow。
- 复杂任务调度系统。
- 对历史 JSONL 的破坏性迁移。

这些能力可以在后续版本中设计，但不应混入第一版架构。

## 用户需求

核心用户需求是：

用户打开一个固定本地网页，看到当前最新的 founder intelligence signals，并能在新一轮抓取和评分后刷新到更新后的结果，而不是每次手动打开一个重新生成的 HTML 文件。

第一版需要支持的使用场景：

- 查看最新一批推荐信号。
- 查看每条 signal 的来源、分数、摘要、相关性理由、建议追问和风险。
- 看到最近一次数据更新时间、输入批次和推荐信号数量。
- 在页面上触发一次数据更新，并在更新完成后看到最新结果。
- 看到更新失败或没有数据时的明确状态。

## 当前实现边界

当前真实实现的 fetch path 只有 RSS：

```text
config/sources.yml
src/fetch_rss.rb
```

`config/sources.yml` 中可能包含 MCP、API、HTML source 的模板或设计信息，但当前 `src/fetch_rss.rb` 只处理启用的 RSS source。Web 应用不得把这些模板当作可运行 source。

当前已有本地 JSONL 存储：

```text
data/store/items/YYYY-MM-DD.jsonl
data/store/runs/YYYY-MM-DD.jsonl
```

这是 append-only handoff format，不是数据库。第一版可以继续使用它，但需要明确读写边界。

当前 `src/build_signals.rb` 同时承担三件事：

- 从 canonical items 生成 signals。
- 写出 `data/signals/latest.json`。
- 写出 Markdown 和 HTML dashboard。

常驻 Web 应用实现时，应逐步把“生成 signal 数据”和“生成 HTML 页面”分离。`data/dashboard/index.html` 应被视为前端模板资产；`src/build_signals.rb` 的 HTML 生成逻辑是过渡期遗留能力，后续不应再把它作为 Web app 主界面的来源。

## 建议的 MVP 形态

第一版推荐采用本地常驻 Web server，加文件型持久数据层。

```text
Browser
   |
   v
Local Web App
   |
   +-> API reads latest signals
   +-> API reads recent run status
   +-> API triggers refresh command
   |
   v
Persistent data files
   |
   +-> data/store/items/YYYY-MM-DD.jsonl
   +-> data/store/runs/YYYY-MM-DD.jsonl
   +-> data/signals/latest.json
```

这个形态保守、贴近现有代码，并且不需要立刻引入数据库。后续如果需要分页、搜索、跨日查询、状态筛选，再升级到 SQLite。

## 推荐功能切分

### 1. Dashboard 页面

页面作为固定入口存在，例如：

```text
http://localhost:4567/
```

它不由每次 pipeline 重新生成，而是由 Web app 提供静态前端资源和 API 数据。

Dashboard 页面不得自行重新定义展示内容和网页样式。第一版应把当前 `data/dashboard/index.html` 视为页面合同：控制台布局、来源文件夹、signal grid、详情面板、profile 配置编辑、source 配置编辑、颜色、间距、响应式行为都应从当前 HTML 迁移到 Web app 前端，只把静态 sample data 改为从 API 读取数据后渲染。

当前 `index.html` 的展示和交互内容包括：

- 浏览器 title：`Founder Intelligence - 信号控制台`。
- 顶部 command bar：产品标题、简短说明、`编辑 user-profile.yml` 入口，以及总抓取、强信号、启用来源三个统计块。
- 左侧 pipeline panel：`RSSHub 抓取`、`标准化`、`规则评分`、`信号输出` 四步流程说明。
- 左侧 source folder panel：按分类展示来源文件夹和来源 logo，点击后打开来源管理 overlay。
- 中间 signal panel：cluster filter、signal 卡片列表、信号分进度条、热度变化和摘要。
- 右侧 detail panel：选中 signal 的标题、信号分、可信度、热度变化、抓取追踪、为什么重要、建议动作和 tags。
- `user-profile.yml` modal：读取、校验并保存 `config/user-profile.yml`，支持导入和下载。
- source folder overlay：展示真实 `config/sources.yml` 来源，启用/停用 RSS source，并支持编辑整份 `sources.yml`。
- 空状态：当前来源或分类无内容时显示明确提示。

当前 `index.html` 的模板资产包括：

- `assets/sample-data.js`，提供 `window.FI_ITEMS`、`window.FI_CLUSTERS` 和 `window.FI_METRICS` 原型数据。
- `assets/brand-logos/*.svg` 和 `assets/brand-logos/36kr.ico`，用于来源文件夹和来源管理 overlay。
- 运行时数据必须来自 API 和 repo 配置文件，不再把 profile/source 状态保存为浏览器 localStorage 产品状态。

当前 `index.html` 的网页样式也应完整保留：

- 纸质控制台底色和网格背景。
- CSS 变量：`--bg`、`--paper`、`--paper-2`、`--rail`、`--ink`、`--muted`、`--soft`、`--line`、`--line-strong`、`--green`、`--green-soft`、`--olive`、`--amber`、`--rust`、`--blue`、`--shadow`。
- `.console` 的两行布局和 18px 外边距。
- `.command-bar` 的标题区加三个统计块布局。
- `.grid` 的三栏工作台布局：来源与 pipeline、signal grid、detail panel。
- `.panel`、`.panel-header`、`.signal`、`.source-folder`、`.folder-overlay`、`.user-md-modal` 等核心视觉样式。
- `@media (max-width: 1180px)` 和 `@media (max-width: 760px)` 中的平板、移动端布局调整。

页面可以新增一个最小刷新控制区，但它不能改变当前控制台的主体结构和视觉风格。刷新控制建议放在 command bar 或 pipeline panel 附近，用现有颜色、边框、字号和间距系统表达当前刷新状态。

注意：模板中出现的 MCP、文件和待绑定 RSSHub 来源是产品界面原型，不代表当前 fetcher 已实现这些抓取能力。实现时必须把可运行来源限定在当前 RSS-only pipeline，未实现来源只能作为禁用态、占位态或未来扩展说明。

Dashboard parity 的验收标准：

- 不得 iframe、嵌入或直接返回 `data/dashboard/index.html` 作为应用主体。
- 不得继续依赖 `assets/sample-data.js` 作为运行时数据源。
- 必须通过 API 数据渲染 signal grid、详情面板、统计信息和可运行来源状态。
- 必须保留 command bar、pipeline panel、source folder panel、signal panel、detail panel、`user-profile.yml` modal 和 source folder overlay。
- 必须保留桌面、平板、移动端三个布局断点下的主体结构。
- 必须把未实现来源显示为禁用态、占位态或未来扩展说明，不得让它们看起来已经可抓取。

字段映射要求：

```text
控制台统计块        <- /api/signals/latest.summary and /api/runs/latest
signal grid        <- /api/signals/latest.signals[]
detail panel       <- selected signal from /api/signals/latest.signals[]
pipeline status    <- /api/refresh/status
source folders     <- /api/sources rows from config/sources.yml
user-profile modal <- /api/profile and config/user-profile.yml
sources editor     <- /api/sources and config/sources.yml
```

### 2. Data API

Web app 应提供数据读取 API：

```text
GET /api/signals/latest
GET /api/runs/latest
GET /api/profile
GET /api/sources
GET /api/health
```

可选 API：

```text
GET /api/items/recent
GET /api/runs
```

第一版 API 可以直接读取现有 JSON 文件，不需要复杂查询层。

`GET /api/signals/latest` 的语义必须是“最近一次成功发布的 signal output”。刷新失败时不得覆盖这个文件，也不得让页面因为失败刷新而清空已有结果。

如果最近一次成功结果不存在，返回：

```json
{
  "status": "empty",
  "message": "No successful signals have been generated yet."
}
```

如果文件存在但 JSON 无法解析，返回 API 错误，并在页面显示“本地 signal 文件损坏或不可读”。这种状态不是空数据。

### 3. Refresh API

第一版页面触发更新模式必须提供：

```text
POST /api/refresh
GET /api/refresh/status
```

`POST /api/refresh` 触发一次完整流水线：

```text
fetch_rss
-> ingest_adapter_output
-> store_canonical_jsonl
-> build_signals
```

这个接口需要保证同一时间只有一个 refresh 在运行。如果已有 refresh 正在运行，应返回当前运行状态，而不是并发启动第二个流程。

第一版 Web server 必须只绑定本地地址：

```text
127.0.0.1
```

`POST /api/refresh` 只接受 same-origin 请求。接口不得接受任何 shell command、脚本路径或任意文件路径参数。

### 4. Pipeline Runner

Web app 不应把抓取、清理、评分逻辑重新实现一遍。它应该调用或复用现有 Ruby 脚本。

第一版 Pipeline runner 的职责是把页面触发的 `POST /api/refresh` 转换成一次串行、可观测、不可并发的现有流水线执行。

Runner 的工作原理：

1. 收到 `POST /api/refresh`。
2. 检查是否已有 refresh 正在运行。
3. 如果没有运行中的任务，则原子创建运行锁，例如 `data/app/refresh.lock`。
4. 将 `data/app/refresh-status.json` 写为 `running`，记录 `started_at`、`current_step` 和空的 command results。
5. 按固定顺序调用现有脚本。
6. 每一步完成后记录 stdout、stderr、exit status、started_at、finished_at 和 duration。
7. 每一步完成后验证对应产物是否存在、可解析、与本次 request 对齐。
8. 如果某一步 exit status 非 0 或产物验收失败，立即停止后续步骤，将状态写为 `failed`，释放运行锁。
9. 如果全部成功但本次没有可展示 signal，将状态写为 `succeeded_empty`，页面显示明确空状态。
10. 如果全部成功且有可展示 signal，将状态写为 `succeeded`，记录 `finished_at`，释放运行锁。
11. 如果发现陈旧 lock，将状态写为 `failed_stale_lock`，要求页面显示可恢复错误。
12. 浏览器通过 `/api/refresh/status` 轮询状态，并在成功后重新读取 `/api/signals/latest`。

Runner 必须在 repo root 下运行命令，所有路径相对 repo root 解析。每一步必须有 timeout，避免页面永久停在 running。日志写入时必须脱敏并限制长度，`refresh-status.json` 只保存摘要和尾部日志。

运行锁内容至少包含：

```json
{
  "request_id": "refresh-20260708T100000Z",
  "pid": 12345,
  "started_at": "2026-07-08T10:00:00+08:00"
}
```

如果 status 是 `running`，但 lock 中 pid 不存在，或运行时长超过 timeout，runner 应按 stale lock 处理。

Runner 应按以下顺序调用现有脚本：

```bash
ruby src/fetch_rss.rb \
  --output data/adapter-output/rss-fetch-latest.json

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

各步骤的语义：

- `fetch_rss` 只抓取当前已实现的 RSS source，输出 adapter result。
- `ingest_adapter_output` 将 adapter result 转成 canonical items。
- `store_canonical_jsonl` 将 canonical items 追加写入 JSONL store，并记录 store run。
- `build_signals` 基于本次 canonical items、用户画像和规则生成最新 signals。

产物验收要求：

- `fetch_rss` 后，`data/adapter-output/rss-fetch-latest.json` 必须存在且 JSON 可解析。
- `ingest_adapter_output` 后，`data/canonical-items/latest.json` 必须存在且 JSON 可解析。
- `store_canonical_jsonl` 后，`data/store/runs/YYYY-MM-DD.jsonl` 必须追加本次 store run。
- `build_signals` 后，`data/app/tmp/<request_id>/signals.json` 必须存在、JSON 可解析，并且 `input_run_id` 与本次 canonical input 对齐。

只有产物验收通过后，runner 才能把临时 signal output 原子发布为：

```text
data/signals/latest.json
```

因此 `data/signals/latest.json` 始终代表最近一次成功发布的 signals。刷新失败不得覆盖它。

`build_signals` 仍可在过渡期继续写出临时 HTML 和 Markdown，用于人工对照。但 Web app 的 dashboard 页面应读取 `data/signals/latest.json`，不应把 `data/dashboard/index.html` 作为页面源或覆盖目标。

后续可以把脚本中的核心函数抽成可复用 Ruby module，但第一版不强制。

## 数据流

MVP 使用页面触发更新模式：

```text
Browser clicks refresh
   |
   v
POST /api/refresh
   |
   v
Pipeline runner starts one refresh job
   |
   v
RSS fetch -> ingestion -> JSONL store -> signal build
   |
   v
data/signals/latest.json and store JSONL are updated
   |
   v
Browser polls /api/refresh/status and /api/signals/latest
```

这个模式让 Web 应用成为主要使用入口，但仍保留当前确定性流水线。

手动命令行运行现有脚本可以作为开发和排障手段保留，但不作为常驻 Web 应用 MVP 的主数据流。

### 后续定时更新模式

定时更新可以作为第二阶段：

```text
Scheduler
   |
   v
Pipeline runner
   |
   v
Persistent data
   |
   v
Web app API
```

注意：当前 `config/sources.yml` 中的 `schedule.refresh_interval_minutes` 还没有被任何调度器消费。实现定时更新前，需要单独设计调度语义。

## 存储策略

### 第一版

第一版建议继续使用文件存储：

- `data/store/items/YYYY-MM-DD.jsonl` 保存 canonical items。
- `data/store/runs/YYYY-MM-DD.jsonl` 保存 store run 记录。
- `data/signals/latest.json` 保存最新 signal 输出。

为了支持 Web app 状态，可以新增：

```text
data/app/refresh-status.json
```

用于记录最近一次页面触发刷新任务的状态：

- `idle`
- `running`
- `succeeded`
- `succeeded_empty`
- `failed`
- `failed_stale_lock`

以及：

- started_at
- finished_at
- current_step
- last_error
- command results
- last_successful_generated_at
- last_successful_input_run_id

`data/app/` 是运行状态目录，不是源代码或文档目录。`data/app/refresh-status.json`、lock、临时文件和日志都应被 git 忽略。

### 后续版本

当需要以下能力时，应考虑引入 SQLite：

- 跨日期查询 items 和 signals。
- 按 source、tag、score、时间范围筛选。
- 保存用户对 signal 的反馈。
- 保存每次评分结果的历史版本。
- 做稳定分页和排序。

SQLite 应作为数据访问层替换，不应改变 fetcher、ingestion 和 scoring 的核心 contract。

## 项目文件架构改动

Web app 化会把当前项目从“一组命令行脚本 + 生成文件”扩展为“命令行 pipeline + 常驻 Web app + 运行状态目录”。第一版应尽量小幅增加目录，不重排现有 pipeline 文件。

### 当前文件角色

当前主要文件角色如下：

```text
config/                       稳定 MVP 配置层；Web app 只显式编辑 user-profile.yml 和 sources.yml
src/fetch_rss.rb              RSS-only fetcher
src/ingest_adapter_output.rb  canonical ingestion
src/store_canonical_jsonl.rb  append-only JSONL storage writer
src/build_signals.rb          deterministic signal builder
data/store/                   append-only item and run store
data/signals/latest.json      最新成功发布的 signal output
data/dashboard/index.html     当前控制台模板来源
docs/web-app/                 Web app feature docs
```

`config/` 仍然是稳定配置层。Web app 第一版只提供 `config/user-profile.yml` 和 `config/sources.yml` 的显式编辑入口，不把 `config/sources.yml` 中的 MCP/API/HTML 模板当作可运行 fetcher。

### 目标文件结构

第一版实现完成后，建议形成以下结构：

```text
src/
  fetch_rss.rb
  ingest_adapter_output.rb
  store_canonical_jsonl.rb
  build_signals.rb
  web_app.rb
  web/
    app.rb
    pipeline_runner.rb
    data_repository.rb
    public/
      index.html
      app.js
      styles.css
      assets/
        brand-logos/

data/
  adapter-output/
    rss-fetch-latest.json
  canonical-items/
    latest.json
  signals/
    latest.json
  store/
    items/YYYY-MM-DD.jsonl
    runs/YYYY-MM-DD.jsonl
  app/
    refresh-status.json
    refresh.lock
    tmp/<request_id>/
    logs/

docs/
  web-app/
    README.md
    architecture.md
    pressure-test.md
    test-plan.md
```

### 新增代码文件

Web app 化应新增以下实现文件：

- `src/web_app.rb`：Web app 启动入口，负责绑定 `127.0.0.1` 和启动本地 server。
- `src/web/app.rb`：HTTP routes，包括首页、静态资源、Data API 和 Refresh API。
- `src/web/pipeline_runner.rb`：封装页面触发 refresh、锁、状态、脚本调用、产物验收、发布和失败恢复。
- `src/web/data_repository.rb`：封装读取 `data/signals/latest.json`、`data/store/runs/*.jsonl` 和来源状态的逻辑。
- `src/web/public/`：从当前控制台模板迁移来的前端资源。

第一版不应把 fetch、ingestion、store、scoring 逻辑复制到 Web app 文件里。Web app 调用或复用现有 pipeline 边界。

### 模板资产迁移

`data/dashboard/index.html` 是当前控制台模板来源。实现 Web app 时，应把它迁移或复制到：

```text
src/web/public/index.html
```

相关静态资产应迁移或复制到：

```text
src/web/public/assets/
```

迁移后需要删除运行时对 `assets/sample-data.js` 的依赖。`sample-data.js` 可以短期保留为 fixture 或视觉参考，但不能作为 Web app 的真实数据源。

`data/dashboard/index.html` 可以在过渡期保留，作为模板来源和人工对照；正式 Web app 首页不应直接返回它，也不应 iframe 它。

### 运行产物目录

`data/app/` 是 Web app 的运行状态目录，用于：

- refresh status。
- refresh lock。
- runner 临时输出。
- runner 日志。

这些文件是本地运行产物，不是源代码、文档或 fixture。它们必须保持 git ignored。

`data/signals/latest.json` 的语义会被收紧为“最近一次成功发布的 signal output”。runner 应先写入 `data/app/tmp/<request_id>/signals.json`，验收通过后再原子发布到 `data/signals/latest.json`。

### 现有文件保留和调整

第一版应保留：

- `src/fetch_rss.rb`
- `src/ingest_adapter_output.rb`
- `src/store_canonical_jsonl.rb`
- `src/build_signals.rb`
- `data/store/**/*.jsonl`

可以调整：

- `src/build_signals.rb` 的 HTML 输出路径可继续用于临时人工对照，但不再产出 Web app 主页面。
- `README.md` 和现有 docs 应补充 Web app 运行入口，但不能把未实现的 scheduler、MCP/API/HTML fetcher 写成已实现能力。

不应调整：

- `config/` 下的 MVP 配置，除非用户明确要求。
- JSONL store 的 append-only 语义。
- RSS-only fetch path 的真实边界。

### 文档结构

Web app feature 相关文档统一放在：

```text
docs/web-app/
```

当前文档分工：

- `README.md`：feature 文档入口。
- `architecture.md`：当前已实现 Web app 的架构、数据流和运行边界。
- `refactor-plan.md`：需求、目标架构、数据流、文件架构和实现边界。
- `pressure-test.md`：架构漏洞、reward hack 路径和修正记录。
- `test-plan.md`：实现验收测试。

后续新增实现计划、变更记录或评审结果，也应放在 `docs/web-app/` 下，并从 `docs/web-app/README.md` 或 `docs/index.md` 链接。

## 组件边界

建议组件边界如下：

```text
src/
  fetch_rss.rb
  ingest_adapter_output.rb
  store_canonical_jsonl.rb
  build_signals.rb
  web_app.rb
  web/
    app.rb
    pipeline_runner.rb
    data_repository.rb
    public/
      index.html
      app.js
      styles.css
```

说明：

- `web_app.rb` 是启动入口。
- `web/app.rb` 定义 routes。
- `web/pipeline_runner.rb` 负责触发现有流水线。
- `web/data_repository.rb` 负责读取 JSON 和 JSONL 文件。
- `web/public/` 放浏览器端资源。

如果后续使用不同 Ruby Web framework，可以调整文件名，但这些职责边界应保留。

## API 合同草案

### `GET /api/signals/latest`

返回 `data/signals/latest.json` 的内容。该文件代表最近一次成功发布的 signal output。

如果文件不存在，返回：

```json
{
  "status": "empty",
  "message": "No successful signals have been generated yet."
}
```

### `GET /api/runs/latest`

返回最近一条 run 记录。第一版可以从 `data/store/runs/*.jsonl` 中读取最新日期和最后一行。

### `POST /api/refresh`

启动一次 refresh。

如果没有任务运行：

```json
{
  "status": "started"
}
```

如果已有任务运行：

```json
{
  "status": "already_running"
}
```

### `GET /api/refresh/status`

返回最近一次 refresh 状态。

```json
{
  "status": "running",
  "current_step": "build_signals",
  "started_at": "2026-07-08T10:00:00+08:00",
  "finished_at": null,
  "last_error": null,
  "last_successful_generated_at": "2026-07-08T09:30:00+08:00",
  "last_successful_input_run_id": "rss-fetch-20260708T013000Z-example"
}
```

`status` 只能取：

```text
idle
running
succeeded
succeeded_empty
failed
failed_stale_lock
```

## 错误处理

Web app 应明确区分以下状态：

- 还没有生成过数据。
- 已有旧数据，但最新刷新失败。
- RSSHub 未启动或不可访问。
- 抓取成功但 canonical items 为空。
- scoring 成功但 signals 为空。
- JSON 文件损坏或无法解析。
- 最新刷新失败但仍有上一次成功结果可展示。
- 运行锁陈旧或 runner 崩溃。

页面展示失败状态时，不应清空已有成功结果。推荐策略是：

- 主区域继续显示最近一次成功 signals。
- 顶部状态栏显示最新 refresh 失败。
- 失败详情保存在 refresh status 中。

错误信息和日志展示必须脱敏。API 不应返回完整 stdout/stderr，只返回摘要、错误分类和截断后的尾部日志。

## 实现顺序

建议按以下顺序实现：

1. 提取 Web app 入口，启动本地 server。
2. 实现只读 API，读取 `data/signals/latest.json`。
3. 实现 profile/source 配置 API，读取并写入 `config/user-profile.yml` 和 `config/sources.yml`。
4. 将当前控制台模板改成稳定前端页面，通过 API 渲染 signal cards、统计信息、来源状态、配置编辑器和详情面板。
5. 实现 refresh status 文件。
6. 实现 `POST /api/refresh`，按顺序调用现有 pipeline 脚本。
7. 加入运行锁，防止并发 refresh。
8. 补充错误状态展示。
9. 再考虑历史 runs、recent items、筛选和 SQLite。

## 测试要求

第一版至少需要覆盖：

- `GET /api/signals/latest` 在有文件、无文件、坏 JSON 三种情况下的行为。
- `GET /api/refresh/status` 在 idle、running、succeeded、succeeded_empty、failed、failed_stale_lock 下的行为。
- `POST /api/refresh` 不允许并发运行。
- pipeline 中某一步失败时，后续步骤不会继续执行。
- pipeline 失败时不覆盖最近一次成功的 `data/signals/latest.json`。
- 页面能在没有 signals 时显示空状态。
- 页面能用当前控制台模板渲染 `data/signals/latest.json` 的 signal 卡片、详情面板和基础统计。
- 页面不得依赖 `assets/sample-data.js` 作为运行时数据源。
- 页面不得 iframe 或直接返回 `data/dashboard/index.html`。

页面触发 refresh 应至少手动验证一次完整流程：

```text
启动 RSSHub
启动 Web app
打开首页
点击刷新
等待任务完成
确认页面出现新 signals
确认 data/store/items 和 data/store/runs 有追加记录
```

## 维护原则

- `config/` 继续视为当前 MVP 的稳定配置层，除非需求明确要求，不在 Web app 中修改它。
- `src/` 是实现层，Web app 应复用当前 RSS-only pipeline，不假设其他 source type 已可运行。
- `data/` 是运行产物层，Web app 可以读取和追加状态文件，但不应破坏已有 JSONL。
- `data/dashboard/index.html` 是当前控制台模板来源，可以在过渡期保留；正式 Web app 应迁移到 `src/web/public/` 或等价静态资源目录，并通过 API 装载真实数据。
- Web app 第一版只绑定 `127.0.0.1`，不提供公网或局域网访问。
- 运行状态、lock、临时文件和日志应写入 `data/app/`，并保持 git ignored。
- 新文档应同步更新 `docs/index.md`，避免架构知识散落。

## 判断标准

当以下条件满足时，可以认为常驻 Web 应用 MVP 完成：

- 用户访问固定本地 URL 即可看到 dashboard。
- 页面不依赖每次重新生成 HTML。
- 新一轮 pipeline 运行后，页面能读取最新 signal 数据。
- RSS-only、确定性评分、append-only storage 等当前边界被保留。
- 失败状态能被页面和 API 清楚表达。
- 后续维护者能从 `docs/index.md` 找到当前架构说明。
