# L4 用户闭环 P0 修复需求、实现与测评

日期：2026-07-13

状态：用户已要求修复。本文将 2026-07-13 真实运行暴露的三个 P0 缺口锁定为本轮范围。

## 1. 问题与需求

### P0-1 来源发现

当前一次 SearchProvider 子查询失败会丢弃此前成功结果；真实数据库中 discovery run 存在但 candidate decision 为零。即使搜索成功，普通网页候选也没有 feed resolver，无法进入 RSS/RSSHub collect 主线。

修复要求：

- 单个查询失败不得丢弃其他成功查询；运行状态必须显式记录 partial/degraded reason。
- 支持从公开网页的 RSS/Atom alternate link 解析可抓取 feed；仍不引入通用 HTML 内容 connector。
- 只有通过真实 connector probe 且产生有效 item 的候选才能进入 probation。
- 下一轮 refresh 必须实际抓取 discovery source，不能只创建数据库记录。

### P0-2 Agent 判断展示

当前后端保存完整 AgentAssessment，但 dashboard 只显示 agent component 和 `valid`，仍用规则文案解释“为什么重要/相关”。

修复要求：

- 新闻详情展示 relevance、novelty、credibility、urgency、counter-signal。
- 展示安全的 `reasoning_summary` 与 evidence spans，不展示 chain-of-thought。
- 同时展示 baseline、Agent component、final score，并明确 Agent 是否改变排序。
- fallback 时显示真实 fallback reason，不伪装成 Agent 已判断。

### P0-3 Bilibili 持续跟踪

当前只识别 `space.bilibili.com/<numeric uid>`，视频/BV/短链无法解析；即便识别 UP 主，也创建 inactive RSSHub binding，却向用户提示“试运行”。

修复要求：

- 支持 numeric UP 主空间 URL。
- 支持 Bilibili 视频 URL；通过受控 resolver 解析视频所属 UP 主。短链若不能安全解析则诚实 unresolved。
- 只有存在 active RSSHub binding 时返回 `probation`；否则返回 `unresolved`。
- probation binding 必须进入 source snapshot，并在 refresh 中真实抓取。
- UI 区分“单条内容已保存”“持续跟踪待解析”“持续跟踪试运行”。

## 2. 实现方案

1. SourceDiscoveryService 将 provider error 改为 per-query 隔离；保留成功 response，再调用 Agent。错误摘要写入 run。
2. candidate probe 先尝试 direct RSS；对 website/publication 读取有界 HTML，仅解析 `<link rel="alternate" type="application/rss+xml|application/atom+xml">`，然后对解析出的 feed 执行 RSSConnector probe。所有 redirect 继续经过 network policy。
3. InboxService 注入 Bilibili resolver 与 tracking probe，便于离线测试。numeric space URL 直接得到 UID；视频 URL 通过 resolver 得到 UID。RSSHub fetch probe 成功才写 active binding 和 probation target。
   本机 RSSHub 使用官方 `chromium-bundled` 镜像，因为 Bilibili creator route 会在 API 受限时回退到浏览器渲染。
4. dashboard 只渲染已持久化的 typed AgentAssessment：五维值、summary、evidence quote、baseline/Agent/final score 和 fallback reason。
5. 不修改 committed `config/`，不增加 HTML 内容抓取，不扩大 Agent 工具权限。

## 3. 可执行验收

- Discovery：三个 query 中一个失败、两个成功时，成功结果仍产生 candidate decision；run 为 `succeeded_partial` 且保留错误。
- Feed resolution：HTML alternate feed 能被解析、probe、加入 probation snapshot；无 feed 的网页被诚实拒绝。
- Bilibili：UP 主 URL 和视频 resolver 都创建 active RSSHub binding；probe 失败只保存 Inbox item，tracking state 为 unresolved。
- Collection：probation RSSHub binding 出现在 snapshot transport config，下一次 fixture refresh 获取 item。
- UI：fixture signal 的五维 Agent 判断、summary、evidence、三段分数与 fallback reason 出现在 dashboard DOM。
- 回归：现有 RSS/RSSHub/Inbox、hybrid ranking、same-origin、atomic publish 和全量测试通过。
- Pressure test：不得以“数据库有 target”“页面显示 probation”“Agent 返回 JSON”冒充端到端成功；权威证据是下一轮 collect item 与浏览器可见解释。

## 4. Pressure test 记录

本轮实现后发现并修复：

1. 通用 SSRF 校验在本机代理环境把 Bilibili 公网域名解析为 `198.18.0.0/15` 并拒绝。修复为只对固定 Bilibili 官方域名/API 使用专用 allowlist，不放宽通用网络策略。
2. 基础 `diygod/rsshub` 镜像没有 Chromium，creator route API 失败后浏览器回退稳定 503。改用官方 `ghcr.io/diygod/rsshub:chromium-bundled`。
3. 旧 Inbox 测试通过注入 `url_validator=lambda` 与只检查 binding 存在，掩盖了真实 DNS、inactive binding 和 route 503。新增真实 route smoke 与 active/snapshot/fetch 断言。
4. Agent JSON 已生成但首页只展示 `valid`。浏览器验收现在要求五维、摘要、证据和排序变化均出现在 DOM。
5. SearchProvider 多查询按整批捕获异常，造成部分成功结果丢失。改为 per-query 隔离，并把 partial error 传播到 workflow degraded summary。
6. 真实候选 feed 出现 chunked `IncompleteRead` 时曾逃出 RSSConnector，导致整轮 discovery 崩溃。candidate probe 现在把所有网络/解析异常收敛为单候选 rejection，其他候选继续。
7. 通用代理把 discovery 域名映射到 RFC 2544 `198.18.0.0/15`。只在 Brave 候选边界允许“域名解析结果为 global 或该代理网段”；直接 IP、localhost 和其他私网继续拒绝，并在 redirect 时复检。
8. 模型可能把 HTML 页面误标为 feed。遇到 content-type/parse failure 时，本地 resolver 会检查页面声明的 RSS/Atom 并重新 probe，模型标签不再成为失败单点。

真实 smoke（2026-07-13）：当前 canonical Bilibili 视频 `BV1FmMi6xEgb` 成功解析 UID `14804670`；creator RSSHub route 返回 HTTP 200；隔离数据库中的 Inbox -> active binding -> snapshot -> fetch 返回 `probation / active / true / ok / 2 items`。应用内浏览器确认 Agent 五维、summary、evidence 和 rank delta 在首页可见。

隔离的真实 discovery smoke 使用当前画像、Brave、真实模型和真实 connector probe：即使 3 个 Search query 中 2 个受限，仍保留 1 个成功 response、形成 5 个 candidate decision，并有 1 个来源通过 RSS/Atom resolution 与真实 fetch，状态为 `validated_probation`；所有数据只写入内存 SourceCatalog。
