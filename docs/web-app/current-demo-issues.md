# 当前 Web App 已知问题

本文记录当前 Web app 中已经确认的问题、已修复的问题，以及剩余问题的修复难度评估。它不是实现方案，而是维护者排查和后续排期时的事实清单。

相关架构说明见 [architecture.md](architecture.md)。历史改造计划见 [archive/web-app/refactor-plan.md](../archive/web-app/refactor-plan.md)。

## 排查时间和范围

- 排查日期：2026-07-08。
- 复查日期：2026-07-09。
- 范围：`src/web/` Web app、RSS-only pipeline runner、当前运行产物和相关配置。
- 重点：页面上的操作是否真的进入后端 pipeline、评分和来源配置。

## 当前结论

当前 Web app 已经不再是静态 HTML demo。它现在具备以下真实功能：

- 首页从 `/api/signals/latest` 读取最近一次成功 signals，不再依赖 `assets/sample-data.js`。
- 点击“刷新”会触发 RSS-only pipeline，并发布新的 `data/signals/latest.json`。
- 页面会展示本次 refresh 的处理数、新增数、重复数，以及推荐队列是否变化。
- 页面编辑 `config/user-profile.yml` 后，下一次 refresh 会使用新 profile 参与评分。
- 页面读取和编辑 `config/sources.yml`，并可启用/停用真实 RSS source。
- 未实现的 MCP/API/HTML/file source template 只能作为不可运行扩展展示，不能被启用为当前 fetch path。

## 已修复问题

| 问题 | 当前状态 | 证据 |
| --- | --- | --- |
| 旧 profile 草稿入口不影响评分 | 已修复。页面入口已改为 `user-profile.yml`，写入 `config/user-profile.yml` | `GET/PUT /api/profile` |
| 来源启停只改浏览器状态 | 已修复。来源列表来自 `config/sources.yml`，启停写回真实配置 | `GET /api/sources`、`POST /api/sources/:id` |
| 无法编辑真实 source 配置 | 已修复。source overlay 内可编辑并保存整份 `config/sources.yml` | `PUT /api/sources` |
| 前端 hardcoded source catalog 与后端 config 漂移 | 已修复。前端不再维护第二份来源真相，UI rows 由后端从 `config/sources.yml` 派生 | `src/web/data_repository.rb` |
| 刷新完成但页面无变化难以解释 | 已缓解。状态栏展示处理、新增、重复数量，并展示 top signal id 是否变化 | `store_summary`、`signal_diff` |
| Refresh API 同步语义误导 | 已缓解。成功响应返回 `200`，前端文案改为“正在刷新/刷新完成” | `src/web/app.rb`、`src/web/public/app.js` |
| refresh status 缺少 run-level 时间 | 已修复。最终状态包含 `started_at`、`duration_seconds` | `src/web/pipeline_runner.rb` |
| `data/app/tmp/` 持续堆积 | 已缓解。成功 refresh 后保留最近 5 次临时目录 | `cleanup_temp_dirs` |
| 旧 `config/rss-sources.yml` 误导维护者 | 已修复。该文件已删除，主流程只使用 `config/sources.yml` | `config/sources.yml` |
| 前端缺少 API 错误兜底 | 已修复基础兜底。网络错误、非 JSON、非 2xx 会展示页面错误 | `fetchJson`、`renderError` |
| same-origin 判断过于宽松 | 已部分修复。现在按启动时的本地 host/port 生成 allowed origins，并拒绝 host 前缀伪装或错误端口；但缺失 `Origin` 的 mutating request 仍会放行，见 V1 | `same_origin?`、`src/web_app.rb` |
| signal score 单位不清 | 已缓解。列表和详情标注总分为 `/100`，详情说明后端 1-5 到 0-100 的换算 | `src/web/public/app.js` |
| profile/source 保存前校验过浅 | 已修复基础语义校验。profile 要有用户和画像词；RSS source 要有可抓取 URL，未实现 source type 不能启用 | `validate_profile_config`、`validate_sources_config` |
| 真实浏览器中 source toggle 失败 | 已修复。WEBrick 不支持浏览器发起的 `PATCH`，前端运行路径改为 `POST /api/sources/:id`，App 内保留 PATCH 兼容 | `src/web/public/app.js`、`src/web/app.rb` |

## 2026-07-09 复查新增漏洞

| ID | 漏洞 | 影响 | 修复建议 | 建议优先级 |
| --- | --- | --- | --- | --- |
| V1 | 写配置和 refresh 接口在缺少 `Origin` header 时会放行 | 默认绑定 `127.0.0.1` 时风险较低；如果用 `--host 0.0.0.0` 或其他非 loopback 地址启动，能访问端口的客户端可绕过浏览器 same-origin 保护，直接写 `config/user-profile.yml`、`config/sources.yml` 或触发 refresh | 强制 Web app 只允许 loopback 绑定；或为所有写接口和 refresh 加本地 token；mutating endpoints 不应默认接受缺失 `Origin` | P1，建议当前修 |
| V2 | `POST /api/sources/:id` 只检查 `source_type: rss`，没有在启停后重新执行完整 `sources.yml` 语义校验 | 一个字段不完整的 disabled RSS source 可以被启用为 runnable，之后 refresh 会把它交给 RSS fetcher，导致抓取失败或错误状态难以解释 | 单个 source 启停后对修改后的整份 config 运行 `validate_sources_config`，失败则不写文件；增加回归测试 | P1/P2，建议当前修 |
| V3 | `POST /api/sources/:id` 使用 `YAML.dump` 重写整份配置 | 启用/停用 source 会丢失 `sources.yml` 中的人类注释、空行和原始格式 | 做格式保真的单字段更新，或改成结构化 source 表单后统一序列化 | P2，可当前修或作为紧随其后的维护项 |
| V4 | refresh 仍是同步 HTTP 请求 | RSSHub 或后续 pipeline 慢时，页面只能等待整个 POST 完成，不能展示 step-level 进度、取消或后台恢复 | POST 创建 refresh job，前端轮询 `/api/refresh/status`；runner 进入后台执行 | P2，若本分支目标是完整 Web app 闭环，建议当前修 |
| V5 | `refresh.lock` 只按 pid 是否存活判断 | 残留 lock 指向当前 Web 进程或 pid 被复用时，refresh 可能长期返回 `already_running` | lock 增加最大年龄或 heartbeat，并结合 `refresh-status.json` 判断；runner 用 `ensure` 释放 lock | P2/P3，建议当前修基础保护 |
| V6 | API 失败时前端只局部展示错误 | `signal-grid` 显示错误，但统计、详情和 source folders 可能仍是旧数据，容易误导用户 | `renderError` 清空或显式标记所有依赖 API 的区域 | P3，小修补 |

## 剩余问题评估

| ID | 剩余问题 | 影响 | 修复难度 | 是否需要代码架构改动 | 是否建议在 `web-app-upgrade` 修复 |
| --- | --- | --- | --- | --- | --- |
| R1 | Mutating API 只做 same-origin 弱保护，缺少 loopback/token 级保护 | 非 loopback 暴露时存在配置写入和 refresh 触发风险 | 小到中 | 否，若引入后台用户/会话才需要架构改动 | 建议当前修。它直接影响本地 Web app 的安全边界 |
| R2 | `POST /api/sources/:id` 启停路径绕过完整 source 校验 | 可把不完整 RSS source 标成 runnable，破坏下一次 refresh | 小 | 否 | 建议当前修。属于小补丁且影响已展示功能真实性 |
| R3 | `POST /api/sources/:id` 会用 `YAML.dump` 重写文件 | 如果用户在 `sources.yml` 中加入注释，后续启停 source 可能丢失注释和原格式 | 中 | 否，但需要选择格式保真策略 | 建议尽快修。当前配置无注释时可非阻塞，但这是配置编辑功能的数据保真问题 |
| R4 | refresh 仍是同步 HTTP 请求 | 长时间抓取会让页面等待整个 POST 完成，无法展示 step-level 进度 | 中高 | 是，需要后台 job 状态和前端轮询 | 建议纳入本分支 P1/P2。刷新是 Web app 核心工作流；若 RSS refresh 稳定很短，可作为非阻塞尾项 |
| R5 | refresh lock 缺少超时/heartbeat 恢复 | 某些残留 lock 或 pid 复用场景可能让刷新长期卡在 `already_running` | 小到中 | 否 | 建议当前修基础超时；更完整的 job 管理可跟 R4 一起做 |
| R6 | API 失败时 UI 会混合旧数据和错误状态 | 用户可能误读旧统计、旧详情或旧来源列表为当前状态 | 小 | 否 | 建议当前修。属于低风险前端小补丁 |
| R7 | source 编辑是整份 YAML 原文编辑，不是字段级表单 | 可用，但对非技术用户不友好；也更容易误改缩进 | 中 | 可能需要 UI 层设计，不一定改后端架构 | 可留后续。当前 MVP 面向本地维护者，YAML 编辑可接受 |
| R8 | 没有 scheduler | 用户必须手动点击刷新 | 高 | 是，需要调度器、状态、错误处理和可能的后台进程 | 留后续。当前分支目标是把静态 demo 升级为可用本地 Web app，手动 refresh 已能闭环 |
| R9 | 未实现 MCP/API/HTML/file fetcher | source templates 只能展示，不参与抓取 | 高 | 是，需要 adapter contract 和真实 fetcher | 留后续。当前 AGENTS 明确 fetch path 是 RSS-only |

## 为什么刷新完成但页面可能不变

点击刷新后，runner 会重新执行：

```text
fetch_rss -> ingest_adapter_output -> store_canonical_jsonl -> build_signals -> publish latest signals
```

如果本次抓取结果全是重复项，`store_summary.appended_items` 会是 `0`。在这种情况下，refresh 是成功的，但输入内容没有新增，top signals 和 score 可能完全不变。

当前页面会显示：

- 本次处理多少条。
- 新增多少条。
- 重复多少条。
- 推荐队列是否变化。

因此，“刷新完成”现在只表示 pipeline 成功完成，不承诺页面内容一定变化。

## 当前分支建议

考虑 `web-app-upgrade` 的目标是把静态 HTML demo 升级成可用 Web app，并保持每项已展示功能真实可用，真实浏览器 smoke 已覆盖 profile modal、source overlay、source toggle 和 source YAML editor。2026-07-09 复查后，V1/V2/V5/V6 更接近已展示功能的可靠性和安全边界，建议在合并前或紧随合并后的修复分支内优先处理。

R2 是否必须在本分支完成，取决于当前 RSS refresh 的实际耗时。如果 refresh 经常超过几秒，应升级为异步 job；如果当前 MVP 仍保持短耗时，可以先把同步 refresh 作为明确限制记录下来。

R7/R8/R9 不建议在本分支展开。它们会明显扩展产品面或 adapter 架构，适合作为后续 feature 分支。

## 验证备注

本轮已完成 Ruby/API/语法级验证，并使用 Codex `@浏览器` in-app browser 完成真实浏览器 smoke。覆盖点包括：

- 打开本地 Web app 并确认 command bar、profile 入口、source folders 渲染。
- 在临时 root 上打开 `user-profile.yml` modal，编辑并保存 profile，确认文件写入。
- 打开 source folder overlay，启用 `github-activity-diygod`，确认页面状态和临时 `sources.yml` 写入。
- 打开 `sources.yml` 编辑器并保存，确认状态显示保存成功。

真实浏览器测试曾发现 `PATCH /api/sources/:id` 在 WEBrick HTTP 层返回非 JSON 错误；当前已改为浏览器运行路径使用 `POST /api/sources/:id`。
