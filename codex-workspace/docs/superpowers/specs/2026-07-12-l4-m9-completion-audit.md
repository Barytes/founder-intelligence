# L4 M2–M9 Completion Audit

日期：2026-07-12

结论：M2–M9 已完成。当前产品默认进入 profile-driven fixed L4 workflow；这不代表 L5 自主 controller，也不代表 API/HTML/MCP/browser connector 已实现。

## 需求闭环

- UserContextEvent 是画像唯一输入；legacy `config/user-profile.yml` 不进入 ProfileStore。
- Profile Compiler 自动处理 pending events，无需用户审 diff；开发者可通过 snapshot audit、Inspector、rollback 与 policy/version 检查行为。
- SQLite ProfileStore/SourceCatalog 是 runtime truth；`config/sources.yml` 只作 bootstrap/import backup。
- SourceTarget 与 AcquisitionBinding 分离。当前真实 acquisition 是 RSS、RSSHub 与 user-supplied Inbox。
- Source Discovery 由 profile/event/cadence 触发，candidate 经本地 URL、connector、yield、dedupe 与 quota 验证后进入 probation；native binding 可进入真实 collect。
- 新闻事实生产继续复用 canonical pipeline；deterministic baseline、bounded candidate pool、evidence-backed AgentAssessment 与代码拥有的 hybrid final score 共同形成 priority queue。
- Web refresh 与 Agent tool 共用固定 L4 runner；当前 dashboard 呈现保持。
- profile/discovery/model/connector failure 均有明确 fallback；canonical/publish failure 不破坏上一成功 artifact。
- 所有实际最终 ordering 可离线 replay；无持久证据的旧 run 明确返回 `not_replayable`。

## 最终门禁

- full pytest suite：247 passed；
- default-on complete workflow、HTTP/API/Inspector/replay/same-origin gates：passed；
- `git diff --check`、`uv lock --check`、Python compileall、JavaScript syntax：passed；
- secret token pattern scan：无匹配；
- SQLite `quick_check`：ok；
- 当前 sources config 与 backup SHA-256 一致：`a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44`；
- migration original rollback anchor、rollback、restore/unpin：passed；
- legacy profile import count：0。

## 最终 pressure-test 处置

F1–F9 已关闭，详见 `2026-07-12-l4-m9-final-pressure-test-findings.md`。浏览器在已完成首轮 UI smoke 后被环境策略阻断继续访问临时 localhost；未绕过该限制，后半段以自动 HTTP/ASGI gate 作为发布证据。该限制不改变代码完成状态，但保留为手工 smoke 的证据边界。
