# L4 M6 Source Discovery 决策记录

日期：2026-07-12

状态：完成。

## SearchProvider 选择

首个真实 adapter 选择 Brave Web Search；`SearchProvider` contract、`FakeSearchProvider`、Agent input/output 和 discovery policy 均不包含 vendor 类型。

选择依据（以 2026-07-12 官方资料为准）：

- Web Search 返回结构化 URL、标题、snippet 和 metadata，支持 `country`、`search_lang`；
- Search plan 当前标价为每 1,000 请求 5 美元、每月含 5 美元 credits、标称 50 QPS；成本和速率仍需按部署账户实时复核；
- 使用 `X-Subscription-Token`，本机只从 `BRAVE_SEARCH_API_KEY` 注入，前端、Agent input、trace 和错误均不保存 secret；
- 普通 API query record 最长保留 90 天；完整或部分搜索结果的长期存储权取决于订阅 plan。因此实现只把最小查询和 normalized candidate evidence 作为产品审计数据，不能把供应商原始响应当成无限期本地语料库；
- 中文/英文参数均受 adapter 支持，但真实中文 discovery quality 尚未用账户 smoke 证明。自动门禁使用中英文 recorded fixture；若真实 smoke 不达标，通过 provider interface 更换或增加本地化 provider，无需修改 Agent contract。

官方依据：

- <https://brave.com/search/api/>
- <https://api-dashboard.search.brave.com/documentation/guides/authentication>
- <https://api-dashboard.search.brave.com/privacy-policy>
- <https://api-dashboard.search.brave.com/documentation/resources/terms-of-service>

## 已实现

- deterministic discovery due：profile hash、显式 follow/share、间隔、coverage/health；
- Profile Compiler 的 discovery hints 只允许非 URL hints；
- profile/event -> 最小查询与显式 event hints，不把完整 profile 或任意 event payload 发给搜索服务；
- typed Source Discovery Agent，无工具权限，无 active status/credential/connector policy 输出字段；
- search/event provenance verifier、URL normalization、public-network policy、identity dedupe；
- injectable connector probe、sample useful-item yield 和 duplicate-ratio gate；
- 新来源只进入 probation，binding 带小型 item quota；
- observation-driven promotion、unhealthy、paused 和 retired 状态机；
- append-only discovery run、candidate decision、reject reason 和 observation trace；
- SearchProvider/Agent failure 使用上一 ResolvedSourceSnapshot，并标记 degraded；
- Brave adapter、Fake provider 和 recorded Agent output 均可离线测试。

## Reward-hack 与安全边界

- candidate 数量受本地 quota 限制；通过数量不会提高来源质量指标。
- zero useful-item yield 和过高 duplicate ratio 会被拒绝；promotion 依赖多次确定性 observation。
- 搜索 snippet、页面内容和 event label 均视为 untrusted data，不能改变工具、network、credential 或 lifecycle policy。
- Agent 不能提交 final source status，也不能构造未出现在 search result 或显式 follow/share event 中的 URL。
- credential、raw request header、provider response body 和模型内部推理不进入持久化 trace。

## 证据

```text
M6 focused (discovery/profile/database): 39 passed
full suite: 207 passed
git diff --check: passed
config/sources.yml SHA-256: a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44
```

D-01 至 D-12 均有 deterministic 或 recorded 自动测试。真实 Brave smoke 为可选门禁，未配置账户时不会阻止离线回归，也不会静默伪造成功。
