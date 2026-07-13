# L4 M5 Connector 与 Inbox 迁移记录

日期：2026-07-12

状态：完成。

## 已实现

- framework-independent Connector contract：capability、validation、fetch、health、cursor、limit、provenance、rate-limit 和错误 taxonomy；
- redirect-aware public-network policy，拒绝 localhost、private/non-global address、超限响应和不支持的 content type；
- `RSSConnector` 复用现有 RSS parser，保持既有 canonical 字段语义；
- `RSSHubConnector` 把平台 SourceTarget identity 与 RSSHub transport binding 分开；
- credential 只以 opaque reference 存储，不进入结果、Agent input 或 trace；
- `InboxService` 与 `POST/GET /api/inbox/items`，支持 URL、标题、备注和可选正文；
- Bilibili creator share 解析为 creator SourceTarget，并生成独立的 probation RSSHub binding；
- 微信文章和无法持续跟踪的分享保留 `origin=user_shared` canonical item，并诚实标记 `unresolved`；
- Connector registry 保留单来源失败，不覆盖其他 connector 的成功结果；
- mutating Inbox API 使用与现有 Web API 相同的 same-origin policy。

## Pressure test

- 来源正文和用户备注只能作为 untrusted data，不能修改 connector 权限或 credential。
- redirect 每一跳重新执行 network policy，避免首个公共 URL 跳转到内网。
- content-length 和实际读取字节均执行上限，失败时不产生半成品。
- RSSHub localhost 只允许显式的本机开发实例；任意 LAN 地址仍被拒绝。
- Inbox 抓取或 resolver 失败不会丢失用户分享的最小事实记录，也不会声称已经订阅。
- SourceTarget 的产品身份不由 transport 类型定义；Bilibili creator 不会被建模为 RSS feed。

## 证据

```text
M5 focused (M2-M5): 42 passed
full suite: 191 passed
config/sources.yml SHA-256 unchanged from the M4 gate
```

C-01 至 C-08 均有自动化测试证据。M4/M5 的 S/C matrix 已完成；真实公网 smoke 保持可选，不作为离线回归门禁。
