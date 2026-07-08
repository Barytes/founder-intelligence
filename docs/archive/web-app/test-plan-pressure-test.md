# 测试方案 Pressure Test

本文 pressure tests `docs/web-app/test-plan.md`，目标是检查测试方案本身是否可能被实现者 reward hack。

## 结论

测试方案已经覆盖 architecture 的主要实现验收面：固定本地入口、Dashboard parity、API 数据装载、RSS-only 边界、latest-success、runner、失败状态、安全边界、runtime artifacts 和文档一致性。

仍需警惕的 reward hack 主要是：

- 用人工截图替代可复查证据。
- 用 mock runner 通过测试，但没有调用真实脚本边界。
- 用 fixture 覆盖真实数据流。
- 只测 happy path，不测失败保留旧结果。
- 把未实现来源做成“看起来禁用”，但实际仍可触发。

## Findings

### P1. Dashboard parity 可能停留在人工主观判断

Risk:

- A2 要求截图和 DOM 检查，但如果只人工看截图，仍可能漏掉交互入口或移动端破碎。

Anti-hack requirement:

- A2 的证据必须包含 DOM selector 检查结果。
- 至少检查 command bar、pipeline panel、source folder panel、signal panel、detail panel、modal、overlay。
- 截图只能作为辅助证据，不能替代 DOM 检查。

Status:

- 已在 A2 写入 DOM selector 检查和三 viewport 证据要求。

### P1. API 数据装载可能被 sample data fallback 掩盖

Risk:

- 页面先用 API，API 失败时 fallback 到 `sample-data.js`，测试时看起来有数据。

Anti-hack requirement:

- A3 必须通过改变 API fixture 观察页面变化。
- A3 必须证明阻断或删除 sample data 不影响真实 API 渲染。

Status:

- 已在 A3 写入 API fixture 改变前后证据和 sample data 阻断要求。

### P1. Runner 测试可能只测 wrapper，不测真实脚本顺序

Risk:

- 实现一个假的 runner status，返回四步成功，但没有调用现有脚本，也没有验证产物。

Anti-hack requirement:

- A6 必须检查 step log、产物文件、store run tail、latest signal hash。
- 成功发布必须经过 `data/app/tmp/<request_id>/signals.json` 到 `data/signals/latest.json`。

Status:

- 已在 A6 写入 step log、artifact checks、mtime/hash 和 store run tail。

### P1. Latest-success 语义可能只在 UI 层伪装

Risk:

- 页面缓存旧数据，但 API 已经覆盖或损坏 `data/signals/latest.json`。

Anti-hack requirement:

- A7.1 必须同时检查 `/api/signals/latest`、`/api/refresh/status` 和文件 hash。
- A6.2 必须证明失败时 `data/signals/latest.json` 不被覆盖。

Status:

- 已在 A6.2 和 A7.1 写入旧结果保留要求；实现验收时应保存 hash 证据。

### P2. RSS-only 边界可能只在文案上禁用

Risk:

- UI 显示未实现 source 为禁用，但 hidden button、API 参数或配置写入漏洞仍可触发未实现 fetcher。

Anti-hack requirement:

- A4 不只看 UI，还检查 runner step log。
- A8.3 禁止 refresh 接收 command、script、path 参数。

Status:

- 已在 A4 和 A8.3 覆盖。

### P2. Security tests 可能只测浏览器，不测 HTTP 请求

Risk:

- 前端按钮不发送跨域请求，但后端仍接受任意 origin 或 shell 参数。

Anti-hack requirement:

- A8 必须用直接 HTTP 请求验证 same-origin、参数拒绝和 runner 未启动。

Status:

- 已在 A8 写入请求和 runner 未启动要求。

### P2. Runtime artifacts 可能被 `.gitignore` 掩盖但仍写错位置

Risk:

- `data/app/` 被忽略，但实现把日志写到其他未忽略路径。

Anti-hack requirement:

- A9 应在成功和失败 refresh 后检查完整 `git status --short`。
- 任何新增运行产物路径都必须解释为 fixture 或加入 ignore 策略。

Status:

- 已在 A9 写入成功、失败后检查 `git status --short`。

### P3. 文档一致性可能变成形式检查

Risk:

- 文档链接存在，但 README 运行命令、端口或边界和 architecture 不一致。

Anti-hack requirement:

- A10 检查运行命令、端口、RSS-only 边界和未实现能力声明。

Status:

- 已在 A10 覆盖。

## Verdict

当前测试方案可以作为实现验收目标，但执行时必须保留证据。没有证据的“通过”不能接受。

实现完成后，应按 A1-A10 逐项记录结果。如果某项无法自动化，必须给出人工验收证据和剩余风险。
