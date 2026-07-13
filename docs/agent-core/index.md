# Agentic Core 当前实现

## Runtime decision

`AgenticCore` 是稳定 facade，默认且唯一委派 `PydanticAIRuntime`。仓库自建 provider 和 turn loop 已删除。PydanticAI 负责模型适配、typed output、tool calls、retry、usage limits 和 framework event projection。

PydanticAI 不接管：

- L4 fixed workflow；
- domain/repository/SQLite；
- connector/network policy；
- source lifecycle；
- evidence verifier；
- deterministic baseline 与 final-score policy；
- atomic publish 和 rollback。

这些层通过 framework-independent contracts 保持可测试、可替换和可审计。

## Bounded Agent nodes

- Profile Compiler：无工具；只接受显式 context events；输出有 provenance 的 profile draft。Correction、unknown、TTL、passive-inference prohibition 由本地 verifier 控制。
- Source Discovery Agent：无工具；只从 normalized search result 或显式 follow/share event 选择 candidate；不能输出 active status、credential 或 connector policy。
- News Assessment Agent：无工具；只看到必要 profile 字段和去除来源声誉字段的 canonical content；输出 dimensions、summary 和 exact evidence spans，不输出 final score/weights。

模型内容均作为 untrusted data 包裹。Runtime trace 会去除 thinking/reasoning 内容；产品审计依赖 typed evidence、hash、version 和 status，不要求保存 chain-of-thought。

## Tool boundary

现有工具继续通过 `ToolRegistry` 做 provider schema + 本地参数校验：

- read signals/canonical/status/latest run；
- `run_refresh_pipeline`；
- write allowlisted Agent artifact。

`run_refresh_pipeline` 和 Web refresh 使用同一个 `PipelineRunner.refresh()` 入口。工具不能传 command、argv、script、path 或任意 shell。

## Configuration and safety

- provider secret 存在本机 `.env`，API/UI 只返回脱敏状态；
- Source discovery secret 使用 `BRAVE_SEARCH_API_KEY` opaque env ref；
- mutating HTTP API 需要 same-origin；
- 本机服务应只绑定 `127.0.0.1`；当前没有远程身份认证；
- Base URL 可配置，用户必须信任目标 provider；
- usage/cost 进入 workflow summary 的结构已存在，真实 provider smoke 需配置本机账户。
