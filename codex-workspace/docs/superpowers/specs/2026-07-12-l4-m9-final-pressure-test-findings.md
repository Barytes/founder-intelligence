# L4 M9 最终 Pressure Test 漏洞清单

日期：2026-07-12

状态：F1–F9 已按用户确认的方案修复并通过最终门禁；F10 由自动 HTTP/ASGI 门禁覆盖，浏览器策略限制仍如实保留。M2–M9 completion audit 已通过。

## 已通过的当前证据

- full suite：最终 247 passed；
- `git diff --check`：passed；
- `uv lock --check`：passed（使用 workspace cache）；
- JavaScript syntax 与 Python compileall：passed；
- SQLite `quick_check`：ok；
- 当前 `sources.yml` 与 migration backup SHA-256 相同；
- 当前 catalog 4 targets，ProfileStore 0 snapshots，证明 legacy profile 未导入；
- source snapshot rollback -> pinned pre-migration snapshot -> restore/unpin smoke 已执行；
- 真实浏览器已验证三栏 dashboard、score provenance、当前信息 degraded 状态与 Inbox unresolved success；并发现、修复 SQLite lazy-init race 与 async refresh/runtime-close 500；
- 浏览器环境随后拒绝继续访问临时 localhost，修复后的 refresh/Inspector 浏览器后半段未宣称通过。

绿测不能覆盖下列需求偏差。

## P0：必须修复

### F1 自动发现来源无法进入真实 collect

证据：`snapshot_to_sources_config()` 只复制 binding 中的 `legacy_source`。M6 自动发现创建的 RSS binding 只有 `connection`、probation quota，没有 `legacy_source`，因此它虽然进入 SourceSnapshot，却会在 collect config 转换时被静默丢弃。

影响：`profile -> 自动发现 -> probation -> 新闻` 的产品主链路不成立；M6/M8 验收被当前测试高估。

修复：为 RSS/RSSHub generic binding 生成兼容 fetch config，保留 target identity、probation quota 和 provenance；Inbox 继续走独立 merge。增加“自动发现 feed 在下一 refresh 产生 canonical item”的端到端 fixture。

### F2 workflow 的 compile/resolve profile 实际只有 resolve

证据：`L4WorkflowRunner._compile_resolve_profile()` 只调用 `resolve_effective_profile()`。Context API 编译失败后，refresh 不会重试；`app.state.profile_service` 后创建时也没有同步回已构造的 runner。

影响：已持久化的新事件可能永远停留在旧 profile/neutral profile，固定 workflow 名称与真实行为不一致。

修复：比较 active snapshot 的 event set 与当前 active events；存在未编译事件时由同一 ProfileService 编译，失败保持旧 active pointer并降级。App 创建/懒加载 service 时同步 runner dependency。增加 compile retry、failure preservation 和 no-op replay tests。

### F3 deterministic fallback run 不能 replay

证据：Inspector replay 只读取 `ranked_signals`。ranking flag off、whole-stage crash 或 calibration 全 fallback 时，baseline artifact 没有持久化为 RankedSignal，API 会返回 `replayed` 但 ordering 为空。

影响：A-05 replay 对最重要的 fallback 路径不成立，且返回状态具有误导性。

修复：所有最终发布 signal（包括 deterministic fallback/outside pool）统一 append RankedSignal；publish 前持久化完整 ordered artifact hash。Replay 校验 ordering/hash，不存在证据时返回 `not_replayable` 而非伪成功。

## P1：应在完成 M9 前修复

### F4 Agent usage/retry/audit 没有贯穿 workflow

证据：Profile Compiler 有临时 audit，但 News Assessment/Source Discovery wrapper 只返回 domain output；`workflow_usage` 永远是空字典。Inspector 无法显示真实 per-stage usage/retry/trace。

修复：为三个 Agent node 统一 `NodeResult(output, usage, trace, replayed)`；repository 保存结构化 audit，不保存 chain-of-thought；WorkflowStepTrace 写入 usage/model/prompt/schema/policy。

### F5 SourceDiscoveryRun 与 WorkflowRun 缺少直接关联

证据：SourceDiscoveryRun 没有 `workflow_run_id`；Inspector 通过 source snapshot ID 猜关联。相同 snapshot hash 复用或 discovery 无候选时可能漏掉 run/candidate/reject trace。

修复：增加 optional `workflow_run_id` contract/schema/index，workflow 调用时显式传入；Inspector 只用直接关联，保留旧数据 fallback 查询。

### F6 Search result retention 与供应商 storage rights 边界不清

证据：决策文档说只保存 candidate evidence，但 `SourceDiscoveryRun.search_responses` 持久化 title、URL、description 的 normalized results。Brave 官方条款说明结果持久化权取决于 plan。

修复：默认持久化 query、request metadata、result URL/hash/rank 和 candidate引用，不保存 description；增加可配置短期 raw-recording store，只在明确具备 storage rights 时开启。更新隐私/retention 文档与 secret scan。

### F7 迁移报告会覆盖初始 rollback point

证据：第一次 apply 正确记录 pre-migration empty snapshot；rollback smoke 后再次 apply 恢复 active snapshot时，固定 `l4-migration-report.json` 被覆盖，`pre_migration_snapshot_id` 变成 post-migration snapshot。

修复：migration history append-only；固定 latest report 保留 `original_pre_migration_snapshot_id`，重复 apply 不覆盖原 rollback anchor。增加 apply -> rollback -> reapply audit test。

### F8 default-on 路径被全局 legacy test fixture弱化

证据：测试 suite 为旧回归设置 `FI_L4_LEGACY_FALLBACK=1`；虽然有 flags unit test和显式 workflow tests，但没有从空环境调用 `load_l4_feature_flags({})` 后走完整 runner 的 default-on integration。

修复：新增独立 default-on install fixture，验证首次 semantic migration、neutral profile、provider unavailable degraded、Inbox 与 safe publish；旧测试继续显式使用 legacy fallback。

## P2：一致性改进

### F9 calibration rejection 后的 assessment 仍以 ASSESSED 状态持久化

影响：最终 score 已 fallback，但 Inspector 可能把被 batch calibration 拒绝的 assessment 看成有效。

修复：先完成 batch calibration 再持久化，或追加明确 rejection decision/status；Inspector 同时展示 model output 与 policy disposition。

### F10 浏览器后半段证据缺失

环境策略在修复后拒绝继续访问临时 localhost。不是代码失败，但浏览器级 refresh/Inspector/replay 尚缺最终截图/DOM 证据。

处理：代码修复后用 ASGI integration + HTTP smoke 完成自动门禁；若浏览器策略恢复，再补一次只读手工 smoke，不以绕过方式切换浏览器。

## 建议执行顺序

1. F1–F3，重新跑 M6/M8/A-05 gates；
2. F4–F7，补完整 audit/retention/migration contracts；
3. F8–F9，增强 default/reward-hack regression；
4. 全量测试、secret scan、migration/rollback smoke、HTTP smoke；
5. 更新 M9 completion audit，再判断是否可以标记 M2–M9 complete。

## 最终整改结果

| Finding | 状态 | 最终实现与反证测试 |
| --- | --- | --- |
| F1 | resolved | Native RSS/RSSHub binding 会转换为 collector contract；target/binding provenance 与 probation quota 保留，fetch 层按单源 quota 截断。 |
| F2 | resolved | workflow 比较 active event IDs，自动编译 pending events；失败时原 active profile pointer 不变并继续用于下游；无 pending event 不重复调用模型。 |
| F3 | resolved | validate/compose 统一持久化实际最终 ordering，包括 flag-off、whole-stage fallback 与合法空排序；旧数据无证据时返回 `not_replayable`。 |
| F4 | resolved | `AgentNodeAudit` 统一约束三个节点的 model/prompt/policy、usage、retry、replay、trace-event kinds 和 error types；不保存 chain-of-thought。Profile audit 随 immutable snapshot 持久化，Discovery 随 run 持久化，News 随 workflow trace 持久化。 |
| F5 | resolved | `SourceDiscoveryRun.workflow_run_id` 由 workflow 显式写入；Inspector 优先直接关联，仅为旧记录保留 snapshot fallback。 |
| F6 | resolved | 持久化搜索响应清空 title/description/rate-limit，只保留 query、request ID、URL、rank 与 result hash；模型选择仍在内存中使用完整临时响应。 |
| F7 | resolved | 每次 apply 生成独立 history report；latest report 保留 `original_pre_migration_snapshot_id`，并可修复旧报告已经覆盖 anchor 的情况。当前真实 DB 已恢复到 migrated snapshot/unpinned。 |
| F8 | resolved | 新增 `load_l4_feature_flags({})` 的完整 runner integration，证明空环境默认进入 L4；legacy fixture 仅覆盖明确兼容路径。 |
| F9 | resolved | assessment 通过 batch calibration 后才写入；全高分 reward-hack fixture 不产生 ASSESSED 记录，并在 node audit 标记 calibration rejection。 |
| F10 | accepted evidence boundary | TestClient/HTTP refresh、Inspector、replay、rollback、same-origin 自动门禁通过。临时 localhost 被浏览器安全策略拒绝后未绕过，因此不虚构补充浏览器证据。 |

最终补充 pressure test 还修复了两项派生边界：合法空 publication 的 replay 证明，以及 generic probation binding 的 quota 真正下沉到 RSS parser。
