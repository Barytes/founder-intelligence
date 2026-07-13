# L4 画像驱动情报工作流测评设计

日期：2026-07-12

状态：M0-M8 已完成，正在进入 M9。本文把 L4 需求和开发计划转化为分层测试、验收证据与 reward-hack 反制。后续每个 milestone 开始前，应先补齐对应测试 skeleton；实现完成后只有本文相关门禁全部通过才能进入下一阶段。

关联文档：

- [L4 需求设计](2026-07-11-l4-profile-driven-intelligence-workflow-design.md)
- [L4 开发计划](../plans/2026-07-12-l4-profile-driven-intelligence-workflow.md)

## 1. 测评原则

1. **行为证据优先**：不以“存在某个类、字段或日志文件”证明功能完成，必须验证真实输入、状态变化、输出、失败和回滚。
2. **确定性测试优先**：domain、policy、permission、schema、migration 和 fallback 使用普通测试；只有语义质量才使用 Agent eval。
3. **默认不依赖外部服务**：自动测试不得要求 API key、真实 LLM、RSSHub、SearchProvider 或公网。
4. **录制与重放**：Agent 与 connector 测试使用 fake/recorded result，保证失败可重现。
5. **负例和 reward hack 与 happy path 同等重要**。
6. **逐层证明**：unit 通过不能替代 workflow、HTTP、browser 和 migration 证据。
7. **旧路径保持可运行**：每个 feature flag 关闭时必须验证当前行为，不接受只证明新路径成功。
8. **发布语义优先**：失败不得覆盖上一版成功 signals、profile 或 source snapshot。

## 2. M0 当前基线

修改前基线命令：

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
```

记录结果：

```text
98 passed, 1 warning in 1.05s
```

Warning 为现有 Starlette/TestClient 对 `httpx` 的 deprecation warning，不是 M0 新增失败。

修改前 `config/sources.yml` SHA-256：

```text
a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44
```

M0 fixture：

```text
tests/fixtures/l4/user-context-events.json
tests/fixtures/l4/profile-snapshot.json
tests/fixtures/l4/canonical-items.json
tests/fixtures/l4/signals.json
tests/fixtures/l4/sources-semantic.json
```

所有 fixture 都是合成数据，不包含真实用户信息或 credential。

M0 最终验收记录（2026-07-12）：

```text
focused: 50 passed, 1 existing deprecation warning in 0.62s
full:    114 passed, 1 existing deprecation warning in 0.84s
diff:    git diff --check passed
sources: a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44
```

最终 sources hash 与修改前记录一致；M0 没有写回或迁移 `config/sources.yml`。

## 3. 测试层级

### T1：纯 domain/unit

- Pydantic schema、enum、hash、policy、feature flags、score composition。
- 不使用数据库、网络、FastAPI 或模型。

### T2：Repository/integration

- temp/in-memory SQLite。
- migration、transaction、idempotency、rollback、concurrency。

### T3：Agent fake/recorded

- PydanticAI fake/test model 或 recorded model output。
- typed output、retry、budget、trace、prompt injection、reward hack。

### T4：Connector fake/recorded

- fake HTTP/search/connector result。
- validation、cursor、rate limit、provenance、partial failure。

### T5：Pipeline fixture

- 使用 synthetic context、profile、sources、canonical item 和 AgentAssessment 跑完整 workflow。
- 验证 step order、fallback、publish 和 run linkage。

### T6：HTTP/API

- FastAPI TestClient。
- same-origin/local authorization、输入验证、兼容 response、无 secret 泄漏。

### T7：真实浏览器

- Dashboard current-context 输入、Inbox、source state、score provenance、degraded state。
- 浏览器 smoke 不能替代 API 和 pipeline 测试。

### T8：可选真实 smoke

- Docker/RSSHub、真实 SearchProvider、真实 LLM、真实公开 URL。
- 只用于验证集成环境，不能作为自动门禁的唯一证据。

## 4. M0 测评矩阵

| ID | 要求 | 权威证据 | 通过条件 | Reward-hack 反制 |
| --- | --- | --- | --- | --- |
| M0-01 | 当前 baseline 已记录 | 本文基线记录 + pytest 输出 | 修改前 98 tests 全绿 | 不用局部测试冒充全量 baseline |
| M0-02 | L4 fixtures 存在且关联正确 | `test_l4_m0_guards.py` | event/profile/run/item IDs 可闭环 | 不只检查文件存在 |
| M0-03 | fixture 不含 secret/真实用户 | fixture 内容 + guard test | 无 token pattern，使用 fixture user | 不以字段名 `secret` 作为唯一判断 |
| M0-04 | sources semantic snapshot 固定 | `sources-semantic.json` + guard test | `yaml.safe_load(current) == snapshot` | 格式差异不算语义变化 |
| M0-05 | sources 文件未被本轮写回 | 修改前后 SHA-256 | hash 完全一致 | semantic equal 不能替代 byte protection |
| M0-06 | 五个 flags 默认关闭 | `test_l4_feature_flags.py` | 未设置 env 时 all false | 不依赖开发者本机 env |
| M0-07 | flag 值严格解析 | feature flag unit tests | 合法真假值通过，未知值失败 | 不把任意非空字符串当 true |
| M0-08 | 开发者可检查 flags | `/api/default-config` test | 返回五个非 secret boolean | 不通过前端 hardcode 冒充 runtime state |
| M0-09 | flags 关闭不改变旧路径 | 全量 existing tests | pipeline/Web/Agent contract 全绿 | 新 tests 不能替代旧 suite |
| M0-10 | 缺失 Origin 的写请求拒绝 | parameterized API test | 所有现有 mutating/chat POST/PUT/PATCH 为 403 | 不只测 `/api/refresh` 一个 endpoint |
| M0-11 | 合法 same-origin 仍工作 | existing Web/workbench tests | profile/source/settings/provider/chat/refresh 成功 | 安全修复不能把产品全部锁死 |
| M0-12 | cross-origin 仍拒绝 | existing security tests | evil origin 返回 403，无文件写入 | 只看 HTTP status 不够，检查副作用 |
| M0-13 | 开发计划已 pressure test | pressure-test 文档 | 漏洞有状态、修正和残余风险 | 不以“未发现”替代逐项检查 |
| M0-14 | M0 完成后全量回归 | pytest + diff check | 全量通过、无 whitespace error | 局部新增测试不算完成 |

验收结论：M0-01 至 M0-14 均为 `proven`。其中 M0-02 至 M0-12 由 50 项 focused tests 证明；M0-09、M0-11、M0-12、M0-14 同时由 114 项 full suite 回归证明；M0-05 由修改前后相同 SHA-256 证明；M0-13 由独立 pressure-test 文档证明。

### M1 PydanticAI 验证与单一 runtime 切换矩阵

| ID | 要求 | 权威证据 | 通过条件 | Reward-hack 反制 |
| --- | --- | --- | --- | --- |
| M1-01 | framework 版本可复现 | `pyproject.toml` + `uv.lock` | 明确主版本上界，frozen sync 成功 | 本机已安装不算复现 |
| M1-02 | OpenAI-compatible provider | factory test | model/base URL/API key/timeout 由现有 config 构造 | 不发真实网络请求冒充单测 |
| M1-03 | typed dependency | context tool test | handler 收到 typed deps 中的 run context | prompt 拼接 context 不算 DI |
| M1-04 | typed structured output | TestModel + FunctionModel tests | 输出通过目标 Pydantic model | dict 后手工 parse 不算 typed runtime |
| M1-05 | function tool 与权限 | recorded tool exchange | ToolRegistry 是最终执行入口，额外参数不执行 handler | framework schema 不能替代本地权限 |
| M1-06 | invalid output retry | invalid/valid + exhaustion tests | 有限重试；耗尽返回 structured error | 只测永远合法输出无效 |
| M1-07 | request budget | looping FunctionModel | 本地 `UsageLimitExceeded` | provider 自报停止不算本地强制 |
| M1-08 | token budget | recorded usage | 超 total token limit 失败 | 只记录 usage 不算限制 |
| M1-09 | tool-call budget | two-call response | 超 tool call limit 失败 | max turns 不能替代 tool-call limit |
| M1-10 | model/tool event capture | trace projection test | tool-call、tool-return、retry、text 可关联 | 只有最终文本不算 trace |
| M1-11 | OTel 本地导出 | in-memory exporter test | 产生有 parent/child 关系的 spans | Logfire UI 截图不算本地证据 |
| M1-12 | offline fake model | TestModel/FunctionModel + network guard | 无 API key、无网络 | 缓存命中不能冒充离线 |
| M1-13 | AgenticCore facade | delegation test | 仍返回既有 `RunResult` | 新增旁路 API 不算兼容 |
| M1-14 | golden compatibility | core recorded exchange tests | tool message/final/usage/max-turn/default context 合同一致 | 只比较 final text 不够 |
| M1-15 | no framework leakage | import scan guard | 业务模块不直接 import `pydantic_ai` | code review 印象不算证据 |
| M1-16 | no private reasoning | redaction test | thinking/reasoning content 不进入 trace | “不会产生”不算保护 |
| M1-17 | existing contracts | focused + full suite | Agent API/tool/current pipeline 全绿 | 新测试不能替代旧 suite |
| M1-18 | spike decision | M1 decision record | 选择、停止条件、残余风险明确 | 依赖已添加不等于框架获批 |
| M1-19 | provider 生命周期 | ownership tests | 只关闭 adapter 自建 client，不关闭 injected model | 测试进程退出不算资源管理 |
| M1-20 | 唯一默认 runtime | constructor test | `AgenticCore` 默认构造 `PydanticAIRuntime`，无 provider 参数 | 可注入不等于默认切换 |
| M1-21 | 旧实现删除 | cutover source guard | provider package、旧 tests、旧 loop symbols 全部不存在 | 不调用的死代码仍算残留 |
| M1-22 | 入口释放资源 | CLI/Web tests + finally code | 成功和异常路径均调用 runtime close | runtime 有 close 方法不代表入口会用 |

## 5. Profile Compiler 验收矩阵

| ID | 场景 | 输入 | 必须输出/行为 |
| --- | --- | --- | --- |
| P-01 | 未初始化 | 无 UserContextEvent | 明确 uninitialized；不得读取写死画像 |
| P-02 | 首次显式输入 | `user_statement` | 合法 ProfileSnapshot，所有字段有 provenance |
| P-03 | 显式纠错 | `profile_correction` | correction 覆盖冲突 inference |
| P-04 | 用户说不知道 | unknown statement | 保持 unknown，不补成确定事实 |
| P-05 | 临时兴趣 | inferred event | confidence + expires_at |
| P-06 | 长期明确偏好 | explicit statement + passive conflict | 不能仅凭 passive behavior 删除 |
| P-07 | 非法字段 | model 输出额外字段 | 本地 schema 拒绝，active snapshot 不变 |
| P-08 | 假 provenance | 不存在 event ID | verifier 拒绝 |
| P-09 | Prompt injection | 用户文本包含工具/系统指令 | 仅作为用户事实数据，不扩大权限 |
| P-10 | Model timeout/over budget | fake failure | 保留上一 active snapshot，写 failure trace |
| P-11 | Replay | recorded output | 不调用 provider，产生相同 snapshot hash |
| P-12 | 并发更新 | 两个 event batch | active pointer 原子切换，无半状态 |

质量 eval 需要衡量：字段 precision、explicit correction adherence、unknown preservation、provenance correctness 和过度推断率。不能以画像字段数量作为质量指标。

## 6. SourceCatalog 与 Connector 验收矩阵

| ID | 场景 | 必须行为 |
| --- | --- | --- |
| S-01 | 导入当前 YAML | semantic field 完整，原文件不变 |
| S-02 | 重复导入 | idempotent，无重复 target/binding |
| S-03 | YAML 格式变化 | semantic identity 不变 |
| S-04 | `source_templates` | 只作为 inactive template/capability，不激活 |
| S-05 | 同一外部实体多个 URL | 合并为一个 SourceTarget，多 binding |
| S-06 | DB 成为默认 | 后续 YAML 不静默覆盖 DB |
| S-07 | 显式 re-import | dry-run summary 后 transaction 更新 |
| S-08 | source toggle | 只更新 catalog/history，不重写 YAML |
| S-09 | invalid binding | 不污染 active snapshot |
| S-10 | snapshot | immutable、带 hash、可关联 workflow run |
| C-01 | RSS parity | 与当前 fixture canonical output 等价 |
| C-02 | RSSHub identity | platform SourceTarget 与 RSSHub transport 分离 |
| C-03 | Inbox URL | 即使持续追踪失败，用户分享 item 仍保存 |
| C-04 | 微信 unresolved | 不宣称已订阅，保留 Inbox path |
| C-05 | redirect/private address | policy 拒绝或明确受控 |
| C-06 | oversize/timeout/type | 分类失败，不写半产物 |
| C-07 | credential | opaque ref，不进入 LLM/trace |
| C-08 | partial connector failure | 其他成功来源仍发布，失败显式记录 |

## 7. Source Discovery 验收矩阵

| ID | 场景 | 必须行为 |
| --- | --- | --- |
| D-01 | profile hash 变化 | 触发 discovery |
| D-02 | 未到间隔且无变化 | 不调用 SearchProvider |
| D-03 | 用户显式 follow/share | 触发 target resolution |
| D-04 | SearchProvider outage | 使用上一 source snapshot，显式 degraded |
| D-05 | 重复结果 | 收敛到现有 SourceTarget |
| D-06 | 恶意 URL/private network | verifier 拒绝 |
| D-07 | 来源内容 prompt injection | 不改变 connector policy/permission |
| D-08 | 批量低质量结果 | quota + probation，不自动 active |
| D-09 | probation 成功 | 满足确定性 threshold 后 promotion |
| D-10 | health 下降 | paused/unhealthy，有 observation 证据 |
| D-11 | 数量 reward hack | 质量以 downstream useful-item yield 衡量 |
| D-12 | trace | query、results、candidate、reject reason 完整 |

## 8. AgentAssessment 与排序验收矩阵

| ID | 场景 | 必须行为 |
| --- | --- | --- |
| R-01 | flag off | 当前 deterministic output parity |
| R-02 | 相关事实项 | 合法 typed assessment + evidence span |
| R-03 | hallucinated span | verifier 拒绝 |
| R-04 | 标题引用 | 不能自动覆盖需要正文支持的 claim |
| R-05 | prompt injection item | 不调用额外工具、不强制高分 |
| R-06 | 所有项高分 | calibration/distribution test 失败 |
| R-07 | 文风可信度捷径 | 不能仅凭措辞判定 credibility |
| R-08 | deterministic Top N 之外的相关项 | exploration pool 能召回 |
| R-09 | duplicate items | 不重复占据优先队列 |
| R-10 | 部分 assessment 失败 | item-level status/fallback 清晰 |
| R-11 | Agent 全部失败 | deterministic-only artifact 合法发布 |
| R-12 | final score | 由 code/policy 计算，model 无权返回权重 |
| R-13 | version linkage | profile/model/prompt/policy/run IDs 完整 |
| R-14 | replay | recorded assessment 产生相同 final ordering |

效果判断至少比较：Top-K precision、exploration recall、用户相关性盲评、错误高分率、证据覆盖率、fallback rate、成本和延迟。文案更流畅不等于 ranking 改善。

## 9. Workflow、发布与兼容验收矩阵

| ID | 场景 | 必须行为 |
| --- | --- | --- |
| W-01 | 正常 L4 run | 固定 step order，所有 snapshot/run 关联 |
| W-02 | concurrent refresh | lock 阻止第二次运行 |
| W-03 | profile failure | baseline 路径可继续或明确停止，上一 profile 不变 |
| W-04 | source discovery failure | 使用上一 source snapshot |
| W-05 | 单 connector failure | succeeded_partial，其他结果发布 |
| W-06 | canonical failure | 不进入评分/发布 |
| W-07 | Agent ranking failure | deterministic fallback |
| W-08 | publish failure | 上一成功 signals 保留 |
| W-09 | stale success | generated_at/run_id/status 一致，不冒充当前 |
| W-10 | Web refresh | 与 Agent tool 使用同一 runner |
| W-11 | flags 独立回滚 | profile/source/ranking 可分别回旧路径 |
| W-12 | current dashboard | 旧字段继续工作，新字段向后兼容 |

## 10. 安全与审计验收矩阵

| ID | 要求 | 必须证据 |
| --- | --- | --- |
| SEC-01 | Mutating API 本机授权 | missing/cross origin 403；same-origin 成功 |
| SEC-02 | Chat 受保护 | chat 可调用工具，必须执行相同 origin policy |
| SEC-03 | Tool arguments 本地验证 | provider schema 之外再次拒绝未知参数 |
| SEC-04 | Secret 隔离 | prompt、trace、error、fixture 无 raw secret |
| SEC-05 | Untrusted content | 来源指令不改变 system/tool policy |
| SEC-06 | Network policy | private IP、redirect、size、type、timeout 受控 |
| A-01 | Run trace | 输入/输出 hash、step、状态、版本完整 |
| A-02 | Profile provenance | 字段可回到 UserContextEvent |
| A-03 | Source provenance | target/binding 可回到 query/share/import |
| A-04 | Score provenance | baseline/Agent/final/policy 可解释 |
| A-05 | Replay | 不调用外部依赖即可复现状态与排序 |
| A-06 | Rollback | active pointer 可切换且留历史 |
| A-07 | No chain-of-thought requirement | 审计依赖 structured evidence，不保存私密推理 |

## 11. Milestone 门禁

### M0

- 本文完成并经用户认可，方可进入 M1。
- M0-01 至 M0-14 全部有当前证据。

### M1

- PydanticAI spike 覆盖 typed output、tool、retry、budget、trace、fake model。
- `AgenticCore` 已切换为 PydanticAI 唯一默认 runtime，自建 provider/loop 已删除。
- 当前 Agent API/tool tests 全绿。
- 新 checkout 安装版本可复现。
- M1-01 至 M1-22 均有当前证据，且 framework import 未泄漏到 runtime adapter 之外。

最终证据：clean-env cutover focused 76 passed；full suite 119 passed；`uv lock --check` 与 `git diff --check` 通过；旧 provider 目录、旧 provider tests 和旧 loop symbols 均不存在。M1-01 至 M1-22 均为 `proven`。

### M2

- Domain/repository tests 全绿。
- migration 幂等、transaction rollback 和损坏处理通过。

最终证据：M2 focused 27 passed；full suite 146 passed；`git diff --check` 通过；source hash 不变。Domain round-trip、extra forbid、stable identity、append-only、migration idempotency/failure、corruption、duplicate event、atomic active switch 均为 `proven`。

### M3

- P-01 至 P-12 通过。
- Profile quality eval 达到实施方案中批准的 threshold。

最终证据：M2/M3 focused 52 passed；full suite 165 passed；P-01 至 P-12 均为 `proven`。质量门禁以 correction adherence、unknown preservation、provenance correctness 和 zero passive over-inference 的 deterministic fixtures 通过；不以字段数量计分。

### M4/M5

- S/C matrix 通过。
- YAML byte protection、RSS parity 和 Inbox fallback 通过。

最终证据：M5 focused 42 passed；full suite 191 passed；RSS/RSSHub identity separation、Inbox Bilibili resolution、微信 unresolved fallback、network/redirect/size/type policy、credential isolation 和 partial registry behavior 均为 `proven`。

### M6

- D matrix 通过。
- SearchProvider 真实 smoke 可选，fake/recorded 自动测试必需。

最终证据：M6 focused 39 passed；provider-neutral SearchProvider/Fake/Brave adapter、profile/event/cadence triggers、outage fallback、URL/identity/quality verifier、probation quota、observation lifecycle、secret isolation 和 append-only trace 覆盖 D-01 至 D-12。

### M7

- R matrix 通过。
- Agent ranking 必须在盲评/Golden dataset 上优于 baseline，不能只通过 schema test。

最终证据：M7 focused 33 passed；full suite 219 passed。Recorded golden 的 Top-1 precision 从 0/1 提升到 1/1，exploration recall 1/1；baseline parity、evidence verifier、prompt injection、duplicate、partial/full fallback、all-high calibration、version linkage 和 replay 覆盖 R-01 至 R-14。

### M8/M9

- W/SEC/A matrix 通过。
- 全量回归、浏览器 smoke、迁移 dry-run、rollback smoke、最终 pressure test 通过。

## 12. 标准命令

M0 与每个 milestone 的基础命令：

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest -q
git diff --check
```

M0 focused：

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest \
  tests/test_l4_feature_flags.py \
  tests/test_l4_m0_guards.py \
  tests/test_unified_web_app.py \
  tests/test_workbench_api.py -q
```

后续 L4 focused：

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv run --extra dev pytest \
  tests/test_l4_domain_contracts.py \
  tests/test_l4_database.py \
  tests/test_profile_compiler.py \
  tests/test_source_catalog.py \
  tests/test_connector_contract.py \
  tests/test_source_discovery.py \
  tests/test_news_assessment.py \
  tests/test_hybrid_scoring.py \
  tests/test_l4_workflow_runner.py \
  tests/test_l4_trace_replay.py \
  tests/test_l4_api.py \
  tests/test_l4_migration.py -q
```

后续文件尚未创建时，不得把该命令失败误报为实现失败；对应 milestone 开始时先建立 test skeleton。

## 13. Completion audit 模板

每个 milestone 完成前逐项填写：

```text
Requirement/ID:
Authoritative evidence:
Current result:
Failure/negative case covered:
Reward-hack countermeasure covered:
Fallback/rollback verified:
Status: proven / contradicted / incomplete / missing evidence
```

只有所有 required ID 为 `proven`，并且没有未解决的 P0/P1 pressure-test finding，才能声明 milestone 完成。
