# Connector 与来源模型

L4 把“追踪对象”和“获取方式”分开：

```text
SourceTarget                  AcquisitionBinding
creator/publication/site     RSS / RSSHub / Inbox / future connector
stable product identity  ->  transport config + opaque credential refs
```

## Connector contract

每个 connector 实现 capability discovery、binding validation、fetch(cursor/limits)、health 和 normalized provenance。统一结果包含 items、structured errors、cursor、rate-limit 与 provenance。

当前实现：

- `RSSConnector`：公共 RSS/Atom，复用现有 parser；
- `RSSHubConnector`：平台 target 与 RSSHub route/instance 分离；显式本机 instance 可用，任意 LAN 地址仍拒绝；
- `InboxConnector`：读取用户分享的 canonical items；持续 tracking 失败不丢内容。

Bilibili 视频链接会先通过固定官方 API 解析为 UP 主 UID，再 probe 本机
`/bilibili/user/video/:uid` route。只有 probe 成功才创建 active RSSHub binding
并显示 `probation`；失败时只保存 Inbox 内容并诚实显示 `unresolved`。本机
RSSHub 使用官方 `chromium-bundled` 镜像，以支持 creator route 的浏览器回退。

API/HTML/MCP/browser connector type 只在 domain enum/未来能力中存在，不代表当前可抓取。

## Network and credential policy

- 每次 redirect 重新验证 URL；
- 拒绝 localhost（RSSHub 明确例外）、private/non-global IP；
- timeout、max bytes、max items、content type 和 redirect count 有界；
- credential 只保存 env reference，不进入 Agent input、trace 或 error body；
- 单 connector failure 不覆盖其他成功来源。

## Discovery

`SearchProvider` 与具体 vendor 解耦；当前 adapter 是 Brave Web Search，自动测试使用 Fake/recorded provider。只向第三方发送最小 query，不发送完整 profile。候选经过 identity dedupe、domain/network policy、connector resolution、probe、sample useful-item yield 和 duplicate check，默认进入 probation 小 quota。

发现查询面向 durable feed（RSS/Atom/official blog）。单个查询失败不会丢弃
其他成功结果；普通网页只有声明可验证的 RSS/Atom alternate link 时才会进入
RSS collect 主线，系统仍不把任意 HTML 页面当作可抓取来源。
