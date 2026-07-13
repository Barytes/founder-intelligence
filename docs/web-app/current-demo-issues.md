# 当前 Web App 已知问题

更新日期：2026-07-12。当前事实以 [architecture.md](architecture.md) 为准。

## 已关闭的旧问题

- 静态 sample data、Ruby/WEBrick、双 refresh runtime：已删除。
- 缺失 Origin 放行 mutating API：已关闭；missing/cross-origin 均 403。
- YAML 是 profile/source source of truth：已关闭；SQLite stores 默认启用，YAML 只保留兼容/显式 import。
- 仅规则评分：已关闭；保留 deterministic baseline，并在有界池内加入 evidence-backed Agent assessment。
- 页面无法解释 Agent 降级：已关闭；refresh status、signal provenance 和 Inspector 均可见。
- 用户分享无法进入 pipeline：已关闭；Inbox minimal canonical item 即使 tracking unresolved 仍会发布。

## 当前限制

| ID | 限制 | 当前处理 | 后续触发条件 |
| --- | --- | --- | --- |
| R1 | 无远程身份认证 | 只绑定 localhost，mutating API same-origin | 多用户/远程部署前必须增加 auth/session/CSRF |
| R2 | Secret 明文存本机 `.env` | API/UI 脱敏，不进 trace | 托管部署前迁移 secret manager |
| R3 | Refresh 是同步 HTTP | lock、step status、failure preservation | 真实延迟不可接受时再设计 background job |
| R4 | 只有 RSS/RSSHub/Inbox connectors | 非 RSS target 可经 RSSHub/Inbox；状态诚实 | 明确平台和合法获取方式后新增 connector |
| R5 | SearchProvider 中文质量未做真实账户 benchmark | 中英文 recorded fixture；provider-neutral contract | 配置 Brave key 后运行真实 smoke/对比本地化 provider |
| R6 | Agent quality evidence 仍以 recorded golden 为主 | schema/evidence/reward-hack/fallback 全覆盖 | 上线前补用户盲评、多模型和成本/延迟样本 |
| R7 | Source YAML import 编辑器仍面向开发者 | SQLite catalog 是默认；Inspector 可控 | 面向普通用户时设计结构化 source management UI |
| R8 | Scheduler 未实现 | 手动 refresh | 连续使用验证需要定时更新后再增加 scheduler |
| R9 | Source rollback 是 pinned pointer | Inspector 可恢复并保留历史 | 需要自动恢复策略时设计显式 unpin/merge UI |

`FI_L4_LEGACY_FALLBACK=1` 只承诺保留一个发布周期，不应被继续扩展为第二套产品路径。
