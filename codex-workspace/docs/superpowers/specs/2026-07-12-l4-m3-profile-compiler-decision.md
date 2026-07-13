# L4 M3 用户事件与 Profile Compiler 实现记录

日期：2026-07-12

状态：完成。

## 实现结果

- `POST/GET /api/context/events`；
- `GET /api/profile/current`、`GET /api/profile/history`；
- append-only `UserContextEvent` 是 source of truth；
- PydanticAI typed `ProfileCompilerOutput`，无工具权限；
- developer policy 限制字段、provenance、correction、unknown、TTL 和 passive inference；
- snapshot 自动生效，无用户 diff 审批；
- recorded replay 不调用 provider且得到同一 profile hash；
- profile flag 关闭时当前 YAML pipeline 不变；开启时只读 active snapshot，未初始化使用 neutral profile；
- signals 写入 `profile_id/profile_hash/profile_status`。

## Pressure test 结论

- Prompt injection 只能作为 untrusted event JSON，Profile Agent 无 function tools。
- 模型 timeout/invalid output 不改变 active snapshot，事件仍保存。
- explicit correction 必须成为被修正字段的最新 provenance。
- explicit unknown 不得被补成模型猜测。
- passive behavior schema 存在但第一版 API 和 verifier 均禁用。
- concurrent compile 只留下完整 snapshot，active pointer 指向其中一个，不产生半状态。
- replay 按内容收敛，不制造重复 snapshot。

## 证据

```text
M2/M3 focused: 52 passed in 2.06s
full suite: 165 passed in 2.99s
git diff --check: passed
config/sources.yml hash unchanged
```

P-01 至 P-12 均为 `proven`。
