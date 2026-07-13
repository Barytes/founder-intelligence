# L4 开发计划首次 Pressure Test

日期：2026-07-12

对象：

- `2026-07-11-l4-profile-driven-intelligence-workflow-design.md`
- `../plans/2026-07-12-l4-profile-driven-intelligence-workflow.md`
- `2026-07-12-l4-evaluation-design.md`

状态：M0 pressure test 与回归已完成。下列修正已进入计划、M0 代码或测评方案；残余风险必须在对应 milestone 继续验证。

## 1. 方法

从以下维度逐项攻击计划：

1. 是否仍在使用旧代码假设；
2. 是否存在“文件/字段存在即算完成”的浅层验收；
3. 是否可能破坏用户未提交修改；
4. Agent 是否能绕过本地权限和验证；
5. fallback 是否可能把旧数据冒充当前数据；
6. 画像、来源和评分是否存在 reward hack；
7. 框架是否反向拥有领域架构；
8. 数据库/YAML 是否形成双 source of truth；
9. 测试是否依赖不稳定外部服务；
10. 每个阶段是否可回滚。

## 2. Findings 与修正

### P0：缺失 Origin 的请求可以调用写接口

问题：当前 `_same_origin` 在请求没有 `Origin` 时返回 true。新增 context、Inbox、source、rollback API 会扩大该漏洞。

进一步问题：`POST /api/chat` 看似是对话，但 Agent tools 可触发 refresh、写 artifact，并产生 API 成本，也属于有副作用入口。

修正：

- 缺失 Origin 默认拒绝；
- 所有现有 POST/PUT/PATCH 写接口与 chat aliases 纳入参数化测试；
- 保留 same-origin 成功测试和 cross-origin 无副作用测试；
- M0 evaluation matrix 增加 SEC-01/SEC-02。

状态：M0 已修正；缺失 Origin、合法同源和恶意跨域场景均已纳入测试，最终全量回归 114 项通过。

### P0：`config/sources.yml` 可能在 M0 或迁移中被重写

问题：当前文件已有用户未提交的格式变化；现有 source toggle 会用 `yaml.safe_dump` 重写整份文件。

修正：

- M0 记录修改前 SHA-256；
- 增加 semantic snapshot fixture；
- M0 全程只读该文件；
- M4 importer 明确只读、idempotent、dry-run；
- SourceCatalog 默认后禁止 YAML/SQLite 双写。

状态：M0 已建立 guard，M4 仍需实现 migration 与 byte-protection tests。

### P1：Feature flag 只写在文档里可能是假护栏

问题：如果代码没有统一解析和可见状态，flag 名称存在不代表默认路径受控。

修正：

- 新增 typed `L4FeatureFlags`；
- 所有 flag 默认 false，未知布尔值失败；
- `/api/default-config` 暴露非 secret runtime 状态；
- `.env.example` 记录全部默认 0；
- 后续每个 milestone 必须通过该对象接入，不得另读同名 env。

状态：M0 已修正；“flag off 与旧 output parity”由全量旧测试持续证明。

### P1：框架迁移不可复现

问题：当前 `.gitignore` 忽略 `uv.lock`。只在 `pyproject.toml` 写宽版本范围，可能让不同开发环境使用不同 PydanticAI 行为。

修正：M1 增加依赖锁定决策和全新 checkout 可复现安装门禁。

状态：M1 必须解决，M0 不引入 PydanticAI dependency。

### P1：SourceCatalog 与 YAML 可能变成双真相

问题：如果每次 refresh 自动导入 YAML，同时 UI 写 SQLite，会形成 last-write-wins 和不可解释覆盖。

修正：

- M4 明确单向 seed import；
- DB 默认后，YAML 变化只通过显式 import 命令进入；
- 不做双向同步；
- `source_templates` 只导入 inactive capability，不激活。

状态：计划已修正，M4 验收。

### P1：Source identity 只用 URL 会随 route/域名变化漂移

问题：一个 Bilibili creator 可能有主页 URL、RSSHub route、API ID 等多个表示；URL 不能作为唯一长期 identity。

修正：M2 优先使用 `(source_kind, provider, canonical_external_id)`，URL 仅作属性；无 external ID 才使用版本化 URL identity strategy。

状态：计划已修正，M2/M4 验收。

### P1：确定性 Top N 预筛选会制造 recall 假成功

问题：Agent 只重排规则高分项，即使精度提升也无法发现规则遗漏的 unknown unknown。

修正：candidate pool 强制加入 source diversity、新 entity、用户分享来源和 bounded exploration；测评同时看 recall。

状态：需求/计划/测评均已覆盖，M7 验收。

### P1：Source Discovery 可能以来源数量 reward hack

问题：模型很容易“发现”大量 URL，让功能看似有效，却增加噪声、成本和脆弱 connector。

修正：quota、probation、dedupe、health、downstream useful-item yield；Agent candidate 不能直接 active。

状态：需求/计划/测评均已覆盖，M6 验收。

### P1：Agent 全部高分会让 hybrid ranking 失效

问题：schema 合法不代表评分有区分度；模型可能把所有内容判为高相关。

修正：negative fixture、分布/calibration test、固定 final formula、baseline 与 Agent 分量分离、盲评和错误高分率。

状态：测评已覆盖，M7 验收。

### P1：旧数据可能冒充当前 fallback

问题：失败后继续展示上一版内容若没有 run/status 标识，会让用户以为本轮成功。

修正：fallback 必须保留 generated_at、input_run_id、workflow_run_id、agent_status 和 degraded reason；发布继续使用 temp + atomic replace。

状态：计划/测评已覆盖，M8 验收。

### P2：PydanticAI 可能反向侵入领域层

问题：在 domain schema、repository 或 connector 中直接使用 framework 类型会增加 lock-in。

修正：只有 `agents/` 和 runtime adapter 依赖 PydanticAI；domain、repository、connector、workflow interface 保持 framework-independent；M1 spike 失败有停止条件。

状态：计划已覆盖，M1/M2 code review 验收。

### P2：真实外部测试可能造成 CI 假失败

问题：RSSHub、搜索、平台页面和 LLM 均不稳定。

修正：fake/recorded 自动测试是 required；真实 smoke 独立 optional，不能替代自动证据。

状态：测评已覆盖。

### P2：用户无需 diff 审批可能演变成不可控制画像

问题：自动生效不等于用户无法纠错或删除；否则会形成隐性监控和画像累积。

修正：显式 correction 优先、provenance、confidence、TTL、rollback；被动行为推断暂不在 M3 第一版启用。

状态：计划已收窄，M3/M9 验收。

## 3. M0 范围核对

| M0 要求 | 当前交付物/证据 |
| --- | --- |
| 独立 evaluation plan | `2026-07-12-l4-evaluation-design.md` |
| acceptance 转测试矩阵 | M0/P/S/C/D/R/W/SEC/A matrices |
| baseline | 修改前 98 passed；M0 后 focused 50 passed、full 114 passed |
| synthetic fixtures | `tests/fixtures/l4/*` |
| flags 默认关闭 | `agentic_core.feature_flags` + tests + `.env.example` |
| flags off fallback | 全量 current suite + 默认值 tests |
| source semantic snapshot | `sources-semantic.json` + guard test |
| 修复 missing Origin | app change + parameterized endpoint test |
| 首次 pressure test | 本文 |

## 4. 尚未解决但不阻塞 M0 的事项

以下是后续 milestone 的显式 gate，不得误称已经实现：

- PydanticAI 依赖和 lock strategy（M1）；
- SQLite/domain schema（M2）；
- Profile Compiler（M3）；
- SourceCatalog migration（M4）；
- Connector/Inbox（M5）；
- SearchProvider 与 Source Discovery（M6）；
- AgentAssessment/hybrid ranking（M7）；
- L4Runner/UI/Inspector（M8/M9）。

## 5. M0 完成判定

只有同时满足以下条件才可将 M0 标为完成：

1. focused M0 tests 通过；
2. 全量 tests 通过；
3. `git diff --check` 通过；
4. `config/sources.yml` 修改前后 SHA-256 相同；
5. M0-01 至 M0-14 均有证据；
6. evaluation plan 已交付用户评审；
7. 不声称 M1 或任何 L4 runtime 功能已经完成。

最终证据：focused 50 passed；full 114 passed；`git diff --check` 通过；`config/sources.yml` 前后 SHA-256 均为 `a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44`。M0-01 至 M0-14 均有可执行证据，且未进入 M1。
