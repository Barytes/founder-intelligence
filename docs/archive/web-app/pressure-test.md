# 常驻 Web 应用 Refactor Plan Pressure Test

本文 pressure tests `docs/web-app/refactor-plan.md`。目标不是证明改造方案已经足够好，而是找出实现时容易钻空子、理解偏差、验收不清或可维护性不足的地方。

## 结论

本轮 pressure test 检查的架构方向是：页面触发更新、RSS-only、复用现有脚本、保留当前 `index.html` 控制台模板的展示内容、交互和样式。

修正前的主要漏洞集中在四类：

- Dashboard parity 的验收标准需要覆盖新控制台模板的交互状态。
- Pipeline runner 的运行状态、失败语义和崩溃恢复还不够具体。
- API contract 还没有覆盖 last-success、空结果、坏数据和日志泄露等边界。
- 测试方案容易被“接口能返回、页面能显示”这种浅层通过 reward hack。

## Findings

### P1. Dashboard parity 容易被表面复刻糊弄

架构要求保留当前 `index.html` 控制台模板；如果只验证页面能显示 signal，很容易漏掉来源管理、详情面板、profile/source 配置编辑和响应式行为。

Reward hack 路径：

- 只保留中间 signal grid，漏掉 command bar、pipeline panel、source folders、detail panel 或 modal。
- 只搬静态 HTML，不把 `assets/sample-data.js` 替换成 API 数据装载。
- 让 MCP、文件或待绑定 RSSHub 来源看起来已经可抓取，突破当前 RSS-only 实现边界。
- 文案层级、空状态、配置保存状态、overlay、平板或移动端布局没有保留。
- 直接 iframe 或读取 `data/dashboard/index.html` 作为页面主体，绕开“Web app 从 API 渲染”的目标。

建议修正：

- 在 architecture 或单独测试文档中增加控制台模板 parity checklist。
- 明确禁止 iframe `data/dashboard/index.html` 或把它作为页面源。
- 要求用 API 数据渲染 signal grid、详情面板、统计信息和可运行来源状态。
- 加一个视觉验收：桌面、平板和移动端截图与当前页面结构、字段、布局一致。
- 加字段映射表：模板中的 `FI_ITEMS`、`FI_METRICS`、来源 catalog 对应 API 或配置的哪个字段。
- 明确未实现来源在 UI 中只能作为禁用态、占位态或未来扩展说明。

### P1. Refresh 成功语义不够明确

修正前的 runner 描述容易被理解为“全部 exit status 为 0 就 `succeeded`”。但某些“业务失败”可能仍然 exit 0。

Reward hack 路径：

- 抓取 0 条 item 也算成功。
- `build_signals` 输出 0 条 signal 也算成功，但页面看起来像正常刷新。
- `data/signals/latest.json` 没有实际更新，runner 仍返回成功。
- 只检查最后一个脚本成功，不检查中间产物是否存在和可解析。

建议修正：

- 为每一步定义产物验收条件。
- `fetch_rss` 后检查 adapter output 存在、JSON 可解析、summary 能反映抓取结果。
- `ingest_adapter_output` 后检查 canonical items 文件存在且 JSON 可解析。
- `store_canonical_jsonl` 后检查 run record 已追加。
- `build_signals` 后检查 `data/signals/latest.json` 存在、JSON 可解析、`generated_at` 或 `input_run_id` 与本次输入一致。
- 明确 0 item 和 0 signal 是 `succeeded_empty`、`warning` 还是 `failed`。

### P1. 并发锁和崩溃恢复不清

修正前的架构提到 `data/app/refresh.lock`，但没有定义锁内容、原子创建、陈旧锁处理和进程崩溃后的恢复。

Reward hack 路径：

- 用普通写文件实现锁，两个并发请求同时通过检查。
- 进程崩溃后 lock 永久存在，应用一直显示 running。
- 删除 lock 但 status 仍是 running，页面状态自相矛盾。

建议修正：

- 用原子文件创建或进程内 mutex 加文件状态双层保护。
- lock 内容包含 pid、started_at、request_id。
- `/api/refresh/status` 检查 running 状态时验证 pid 是否仍存在。
- 定义 stale lock 策略：例如超过超时时间且 pid 不存在时标记 `failed_stale_lock`。

### P1. API 没有 last successful result 语义

修正前的架构说刷新失败时主区域继续显示最近一次成功 signals，但 API contract 只有 `/api/signals/latest` 和 `/api/refresh/status`，没有说明 latest 是“最新成功”还是“最新尝试”。

Reward hack 路径：

- 刷新失败后页面清空，因为 latest 被覆盖或读取失败。
- 页面展示旧数据，但不告诉用户最新刷新失败。
- API 混合返回旧 signals 和新失败状态，前端无法判断数据时效。

建议修正：

- 明确 `/api/signals/latest` 返回最近一次成功 signal output。
- refresh 失败不得覆盖最近一次成功 signals。
- status 中增加 `last_successful_generated_at` 和 `last_successful_input_run_id`。
- 页面同时展示数据时间和最新刷新状态。

### P2. Runner 的运行环境没有写死

架构列了命令，但没有明确 cwd、Ruby 执行器、RSSHub 前置条件、超时、取消策略和日志路径。

Reward hack 路径：

- 从错误 cwd 启动，脚本找不到相对路径。
- RSSHub 没启动，fetch 失败后错误信息不可读。
- 某一步卡死，页面一直 running。
- stdout/stderr 全量塞进 status JSON，文件无限膨胀。

建议修正：

- runner 必须以 repo root 为 cwd。
- refresh 前检查 RSSHub health 或至少把 RSSHub 连接失败识别为明确错误。
- 每一步定义 timeout。
- command result 只保存尾部日志或单独落日志文件，status JSON 保持小而可读。

### P2. 日志和错误信息可能泄露敏感信息

RSSHub 可能使用 `.env` 中的 token。架构要求保存 stdout、stderr，但没有要求脱敏。

Reward hack 路径：

- API 直接返回完整 stderr。
- 页面或 JSON 文件泄露 token、环境变量或本地路径。

建议修正：

- 对 `token`、`authorization`、`GITHUB_ACCESS_TOKEN` 等字段做基础 redaction。
- `/api/refresh/status` 默认返回摘要，不返回完整日志。
- 完整日志如需保存，应放本地文件并限制 UI 展示长度。

### P2. Web app 绑定地址和访问边界不清

文档说本地 Web app，但没有明确 bind 到 `127.0.0.1`，也没有说明 POST refresh 是否需要 CSRF 或 origin 限制。

Reward hack 路径：

- server 绑定 `0.0.0.0`，局域网其他设备可触发抓取。
- 任何网页都能向本地 `POST /api/refresh` 发请求。

建议修正：

- 第一版明确只绑定 `127.0.0.1`。
- `POST /api/refresh` 只接受 same-origin 请求。
- 不提供任何可传入 shell command 的参数。

### P2. Feature 文档和实现文档边界还可以更清晰

当前 architecture 同时写需求、架构、API、测试。实现前还需要拆出更可执行的测评方案。

Reward hack 路径：

- 实现者只按“实现顺序”写代码，忽略测试要求。
- 测试只覆盖 happy path。

建议修正：

- 在 `docs/web-app/` 下新增 `test-plan.md`。
- 把 parity、runner、API、failure states 分成可逐项验收的测试条目。
- 每个测试条目说明 fixture、操作、预期结果。

### P3. `data/app/` 运行产物是否纳入 git 没有说明

架构建议新增 `data/app/refresh-status.json`，但没有说明是否应被 git 忽略。

Reward hack 路径：

- 实现后把本地 refresh 状态、日志或 lock 文件提交进仓库。

建议修正：

- 检查现有 `.gitignore`。
- 明确 `data/app/*.json`、`data/app/*.lock` 或日志文件是否应忽略。
- 如果需要保留示例，应使用 fixture，而不是实际运行状态。

## 本轮修正落点

本 pressure test 的修正方向已经落到以下文档：

1. `docs/web-app/refactor-plan.md`：补充 Dashboard parity、last-success semantics、runner 成功条件、锁和超时策略、本地访问边界、日志脱敏和运行产物策略。
2. `docs/web-app/test-plan.md`：把 Dashboard parity、API、runner、错误状态、本地访问和运行产物写成可验收测试。
3. `.gitignore`：忽略 `data/app/`，避免 refresh status、lock、tmp 和 logs 被提交。

后续如果 architecture 或实现继续变化，应重新运行本 pressure test，并把新漏洞记录在本文或新的 audit 文档中。
