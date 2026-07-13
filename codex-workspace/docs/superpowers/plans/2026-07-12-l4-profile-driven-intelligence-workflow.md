# L4 画像驱动情报工作流开发计划

日期：2026-07-12

状态：待用户评审。需求基线为 [`../specs/2026-07-11-l4-profile-driven-intelligence-workflow-design.md`](../specs/2026-07-11-l4-profile-driven-intelligence-workflow-design.md)。本计划通过后，仍须先完成独立的可执行测评方案与 pressure test，再开始功能代码实施。

## 1. 目标

在不破坏当前 Python refresh、canonical item、JSONL store 和新闻看板的前提下，将现有 L3/L3.5 系统升级为固定、可回放、可降级的 L4 workflow：

```text
真实用户信息
-> PydanticAI Profile Compiler
-> ProfileSnapshot
-> SourceCatalog / Source Discovery
-> ConnectorResolver / 多 connector 抓取
-> canonical items
-> 确定性基础评分
-> PydanticAI News Assessment
-> hybrid ranking
-> 当前新闻看板
```

完成后，`config/user-profile.yml` 和 `config/sources.yml` 不再是动态 runtime source of truth；RSS 只是一种 connector；Agent 参与画像、来源和评分，但不能改变固定 workflow、权限边界或最终评分公式。

## 2. 当前代码事实与保护对象

当前必须保护的主线：

- `web_workbench.app` 是唯一 FastAPI 后端。
- Web 和 Agent refresh 共用 `agentic_core.pipeline.runner.PipelineRunner`。
- `PipelineRunner` 已实现 lock、status、部分来源失败、临时产物、安全发布和失败保留上一版 signals。
- `fetch_rss.py`、`ingest_adapter_output.py`、`store_canonical_jsonl.py`、`build_signals.py` 已有 parity 测试。
- `data/canonical-items/latest.json` 和 append-only JSONL 是现有事实层。
- `data/signals/latest.json` 是当前 dashboard 的发布合同。
- 当前 `AgenticCore.run()` 和 Agent API 已有测试覆盖。
- 当前工作树中的 `config/sources.yml` 存在用户未提交修改，迁移过程中必须原样保护。

禁止采用的迁移方式：

- 一次提交同时更换 Agent 框架、数据库、来源系统、评分器和 UI；
- 先删除现有 runner，再补失败语义；
- 自动把当前硬编码 `user-profile.yml` 导入成真实用户；
- 让 Agent 直接重写 committed YAML；
- 为了接入框架重写 canonical item 或 signal contract；
- 用真实外部 LLM、RSSHub 或网页作为自动化测试的必需依赖。

## 3. 开发组织方式

该功能属于长期、多阶段开发，必须使用独立 worktree 和 `codex/` 前缀分支。推荐：

```text
branch:   codex/l4-profile-driven-workflow
worktree: ../founder-intelligence-l4
```

如果后续并行开发 connector，使用独立 feature worktree，例如：

```text
codex/l4-inbox-connector
codex/l4-rsshub-resolver
codex/l4-news-assessment
```

公共 domain schema、repository interface、workflow state、connector contract 和 signal contract 必须先在 L4 基础分支稳定，再允许并行 feature 接入。

每个 milestone 独立提交；任何 milestone 只有在本阶段测试、兼容测试、`git diff --check` 和 pressure-test checklist 通过后才能进入下一阶段。

## 4. 推荐代码结构

```text
src/agentic-core/agentic_core/
  agents/
    profile_compiler.py
    source_discovery.py
    news_assessment.py
  connectors/
    base.py
    rss.py
    rsshub.py
    inbox.py
    resolver.py
  domain/
    user_context.py
    profiles.py
    sources.py
    assessments.py
    workflow.py
  storage/
    database.py
    migrations.py
    user_context_repository.py
    profile_repository.py
    source_repository.py
    assessment_repository.py
    workflow_repository.py
  workflows/
    l4_runner.py
    policy.py
    trace.py
  pipeline/
    runner.py                  # 保留现有发布/失败语义，逐步委托 L4Runner
    build_signals.py           # 拆出 baseline scoring 与 hybrid composition
  core.py                      # 保留兼容 facade，内部迁移到 PydanticAI

src/agentic-core/web_workbench/
  app.py
  dashboard_repository.py     # 逐步改为调用新 repositories

tests/
  fixtures/l4/
  test_l4_domain_contracts.py
  test_l4_database.py
  test_profile_compiler.py
  test_source_catalog.py
  test_connector_contract.py
  test_source_discovery.py
  test_news_assessment.py
  test_hybrid_scoring.py
  test_l4_workflow_runner.py
  test_l4_trace_replay.py
  test_l4_api.py
  test_l4_migration.py
```

原则：domain、repository、connector 和 workflow interface 不导入 PydanticAI；只有 `agents/` 与 runtime adapter 依赖框架。

## 5. 总体里程碑

| Milestone | 结果 | 是否改变用户行为 |
| --- | --- | --- |
| M0 | 测评方案、基线、feature flag、工作树保护 | 否 |
| M1 | PydanticAI 验证、单一 runtime 切换与旧 loop 删除 | 合同不变 |
| M2 | L4 domain contracts、SQLite、repositories、trace skeleton | 否 |
| M3 | 真实用户事件与自动 ProfileSnapshot | 可选 flag |
| M4 | SourceCatalog 接管现有 RSS sources | 可选 flag |
| M5 | Connector contract、RSS/RSSHub、Inbox | 可选 flag |
| M6 | Source Discovery 与来源生命周期 | 可选 flag |
| M7 | Agent assessment 与 hybrid ranking | 可选 flag |
| M8 | L4 固定 workflow、API 与现有 dashboard 接入 | 是 |
| M9 | Run Inspector、eval、数据路径默认切换和文档修正 | 是 |

推荐发布切线：

- **L4 alpha**：M0–M4。真实画像 + SourceCatalog，仍使用当前 RSS 和确定性评分。
- **L4 beta**：M5–M8。自动来源、Inbox、Agent ranking、当前 dashboard。
- **L4 complete**：M9 全部门禁通过，并完成最终 pressure test。

## 6. M0：先建立测评与迁移护栏

### 目标

在编写功能代码前，固定当前行为、L4 acceptance、feature flag 和回滚方式。

### 任务

1. 新建独立 L4 evaluation plan：

   ```text
   codex-workspace/docs/superpowers/specs/2026-07-12-l4-evaluation-design.md
   ```

2. 将需求文档中的 profile、source、scoring、audit、security、compatibility 条款转换为可执行测试矩阵。
3. 记录当前全量测试基线：

   ```bash
   uv run --extra dev pytest -q
   git diff --check
   ```

4. 增加 L4 fixture 目录，复制最小 canonical items、signals、profile 和 source semantic fixture；不得复制 secret 或真实用户数据。
5. 定义 feature flags，初始全部关闭：

   ```text
   FI_L4_PROFILE_ENABLED=0
   FI_L4_SOURCE_CATALOG_ENABLED=0
   FI_L4_SOURCE_DISCOVERY_ENABLED=0
   FI_L4_AGENT_RANKING_ENABLED=0
   FI_L4_INBOX_ENABLED=0
   ```

6. 定义每个 flag 的 fallback：关闭时完整走现有代码路径。
7. 为当前 `config/sources.yml` 计算 semantic snapshot fixture；只读取，不格式化、不写回。
8. 在增加更多 mutating API 前，修复当前缺少 `Origin` 仍可通过写请求检查的问题，或引入本机 session token；该安全边界必须有独立回归测试。
9. 对本开发计划执行首次 pressure test，重点检查需求遗漏、错误依赖顺序和 reward-hack 测试缺口。

### 验收门禁

- 当前全量测试通过。
- 每个新能力有至少一个失败路径和 reward-hack case。
- flags 全关时输出与当前 baseline 一致。
- `config/sources.yml` byte-for-byte 未被修改。
- 新增 context、Inbox、source 和 rollback API 前，mutating request 已有可靠本机授权边界。
- 用户批准 evaluation plan 后才能进入 M1。

### 回滚

M0 只增加 docs、fixtures 和未启用配置，不改变 runtime。

## 7. M1：PydanticAI 验证、单一 runtime 切换与旧 loop 删除

### 目标

证明 PydanticAI 能覆盖当前 Agent Core 的真实能力并满足 L4 typed node、trace、budget 和测试需求；验证通过后立即切换为唯一 Agent runtime，删除自建 provider 与 Agent loop，不保留双路径 fallback。

### 任务

1. 在 `pyproject.toml` 中以明确版本范围加入 PydanticAI 和测试所需依赖。
2. 明确依赖锁定策略。当前 `.gitignore` 忽略 `uv.lock`；在引入快速演化的 Agent framework 前，必须决定提交 lockfile，或用等价 constraints/可复现构建机制锁定实际版本。
3. 编写最小 spike，覆盖：

   - OpenAI-compatible provider；
   - typed dependency；
   - typed structured output；
   - function tool；
   - invalid output retry；
   - request/token/tool-call limits；
   - model/tool event capture；
   - fake/test model；
   - OpenTelemetry span export 到本地测试 collector 或 in-memory exporter。

4. 新增 `PydanticAIRuntime`，不让业务代码直接实例化 framework Agent。
5. 保留 `AgenticCore` 类和现有 `run()` 返回合同作为兼容 facade。
6. 将现有 tools 通过 adapter 注册到 PydanticAI；handler 与本地 ToolRegistry 权限验证暂时保留，避免迁移时扩大权限。
7. 在删除旧实现前运行 recorded parity；删除后把同一交换固化为 golden contract tests，持续验证：

   - tool name/arguments；
   - tool result 注入；
   - final output；
   - usage；
   - max-turn/request limit；
   - errors；
   - trace events。

8. 决定 Logfire 只作为可选 UI，默认 trace 走 OpenTelemetry/local artifact，避免运行时依赖商业服务。
9. `AgenticCore` 默认构造 `PydanticAIRuntime`，不再接受 legacy provider 注入。
10. 删除 `agentic_core/providers/`、旧 loop body 与只验证旧 provider 的测试；源码 guard 阻止这些符号回归。
11. Web 和 CLI 每次运行后关闭 runtime 自建的 provider client。

### 主要文件

```text
pyproject.toml
src/agentic-core/agentic_core/runtime/pydantic_ai_runtime.py
src/agentic-core/agentic_core/core.py
src/agentic-core/agentic_core/tools/*
tests/test_pydantic_ai_runtime.py
tests/test_core_loop.py
tests/test_workbench_api.py
```

### 验收门禁

- 现有 Agent API、tool contract 和 tests 不回归。
- fake model 测试不需要网络和 API key。
- 全新 checkout 能安装与 CI/开发相同的 framework 版本。
- 无效 structured output 能有限重试并产生结构化失败。
- request/token/tool-call budget 可在本地强制执行。
- trace 能关联 model call 与 tool call。
- spike 评审确认没有明显 provider/framework lock-in 泄漏到 domain。
- `AgenticCore` 只有 PydanticAI 默认路径；源码中不存在 `ProviderResponse`、`ProviderToolCall`、`OpenAICompatibleProvider`、`build_provider` 或自建 turn loop。

### 停止条件

如 typed output、OpenAI-compatible provider、工具权限或 test model 无法满足要求，则在删除旧实现前停止切换。切换完成后不在 runtime 中保留 legacy fallback；回滚通过版本控制恢复整个已验证版本，不维护两套在线实现。

## 8. M2：Domain contracts、SQLite 与 repository

### 目标

建立 framework-independent 的 L4 数据合同和本机持久化层，不改变当前 pipeline 输入。

### 技术选择

- 使用 Python stdlib `sqlite3`，避免第一版引入 ORM。
- 数据库路径：`data/app/founder-intelligence.db`，必须 gitignore。
- 启用 `foreign_keys=ON`；本机单进程模式使用 WAL。
- 使用显式、顺序编号 migration 和 `schema_migrations` 表。
- 所有 repository 操作使用 transaction；active snapshot 切换必须原子化。
- 时间统一存 ISO 8601 UTC，API 可转换为本地时区。

### 任务

1. 定义 Pydantic domain models：

   - UserContextEvent；
   - ProfileSnapshot / EffectiveProfile；
   - SourceTarget；
   - AcquisitionBinding；
   - ResolvedSourceSnapshot；
   - AgentAssessment；
   - RankedSignal score provenance；
   - WorkflowRun / WorkflowStepTrace。

2. 为所有 model 使用 `extra="forbid"`、version field 和明确 enum。
3. 建立数据库初始化、migration 和 transaction helper。
4. 实现 repositories，禁止 Web route 或 Agent 直接写 SQL。
5. 支持 in-memory SQLite 以便测试。
6. 定义 content hash、profile hash、source snapshot hash 和 idempotency key。
7. 定义稳定 SourceTarget identity：优先使用 `(source_kind, provider, canonical_external_id)`，URL 只作可变属性；没有 external ID 时才使用经过规范化、带版本的 URL identity strategy。
8. 定义 append-only 与可变状态边界：

   - UserContextEvent 与 trace append-only；
   - ProfileSnapshot immutable；
   - active pointer 可变；
   - SourceTarget/Binding 状态通过 history 可追溯；
   - canonical JSONL 暂不迁移。

9. 增加数据库损坏、migration 失败、重复 event、transaction rollback 测试。

### 验收门禁

- domain model round-trip 与 invalid-extra tests 通过。
- migration 可从空库重复运行且幂等。
- 写入失败不会留下半个 active snapshot。
- repository tests 不依赖 FastAPI 或 PydanticAI。
- 数据库不存在时可自动初始化；损坏时明确失败，不静默重建丢数据。

## 9. M3：用户事件与 Profile Compiler

### 目标

让真实用户输入成为 source of truth，生成自动生效、可回放的 ProfileSnapshot；不再把硬编码画像当默认用户。

### 任务 A：Event ingestion

1. 新增 API：

   ```text
   POST /api/context/events
   GET  /api/context/events
   GET  /api/profile/current
   GET  /api/profile/history
   ```

2. 第一版只开放显式事件：`user_statement`、`goal_update`、`shared_content`、`profile_correction`、follow/unfollow。
3. 被动行为事件先定义 schema，不在第一版自动推断，避免隐性监控范围膨胀。
4. 所有 event 记录 origin、explicitness、occurred_at 和 supersession。

### 任务 B：Profile Compiler

1. 实现 `ProfileCompilerInput` 和完整 `ProfileCompilerOutput`。
2. 使用 PydanticAI typed output；不让模型返回 YAML patch。
3. 输入仅包含：相关 event、上一版 snapshot、允许修改字段、policy 和字段说明。
4. 本地 verifier 检查：

   - 所有字段来自允许列表；
   - provenance event 存在；
   - explicit correction 优先；
   - inferred field 有 confidence/TTL；
   - 未知信息没有被强制补齐；
   - token/request budget 未超限。

5. 验证通过后 transaction 内写 snapshot 并切换 active pointer。
6. 失败时保留上一版 active snapshot，并记录 failure trace。
7. 增加 replay：提供 recorded model output 时不调用 provider。

### 任务 C：Pipeline compatibility

1. 增加 `ProfileRepository.resolve_effective_profile()`。
2. flag 关闭：runner 继续读当前 YAML。
3. flag 开启：runner 读取 active snapshot；未初始化时生成明确的 neutral/unpersonalized runtime profile，不虚构兴趣与目标。
4. 将 `profile_id` 和 profile hash 写入 signals contract。
5. 暂时保留旧 `/api/profile` YAML route，标为 compatibility/developer route，不作为产品主要入口。

### 主要测试

- 初次创建、更新、纠错、supersession；
- inferred TTL；
- 无 event 时 uninitialized；
- 明确“不知道”不被补全；
- invalid provenance；
- prompt injection in user content；
- Agent timeout/invalid output；
- concurrent active switch；
- recorded replay；
- flag on/off parity。

### 验收门禁

- 没有真实 event 时不使用当前写死画像。
- 用户不审批 diff，合法 snapshot 自动生效。
- 开发者可查看完整 structured change 与 provenance。
- Profile Agent 失败不阻断确定性 baseline refresh。

## 10. M4：SourceCatalog 接管现有 RSS source

### 目标

在不改变抓取结果的情况下，把动态来源真相从 YAML 迁到 SQLite SourceCatalog。

### 任务

1. 实现 `SourceRepository`、状态历史和 `ResolvedSourceSnapshot`。
2. 编写只读 YAML seed importer：

   - 解析当前 `config/sources.yml`；
   - 按 semantic identity 导入；
   - 不格式化、不写回原文件；
   - 重复执行不创建重复 SourceTarget/Binding；
   - 保留 enabled、priority、category、tags、schedule、connection 和 notes；
   - 将 `source_templates` 导入为 inactive template/capability record，不得误建为 active SourceTarget；
   - 记录 import source hash 与时间。

3. 将现有 RSS source 映射为：

   ```text
   SourceTarget + AcquisitionBinding(connector_type=rss|rsshub)
   ```

4. 在每次 refresh 开始时生成 temp `ResolvedSourceSnapshot`。
5. 修改 `fetch_rss` 与 ingestion，使其接受 snapshot/config object 或 temp path，不再在内部固定读取 committed YAML。
6. flag 关闭时仍走旧 YAML；flag 开启时 snapshot 输出必须与 YAML semantic output 等价。
7. Dashboard source API 改为 repository facade，同时保留兼容响应字段。
8. Source toggle 改为写数据库状态，不再 `yaml.safe_dump` 整份文件。
9. 明确单向迁移语义：SourceCatalog 默认启用后成为唯一动态真相；后续 YAML 修改必须通过显式 import 命令进入 catalog，不做静默双向同步，也不在每次 refresh 自动覆盖数据库状态。

### 主要测试

- 当前 YAML semantic import；
- 用户修改的 YAML 被完整导入；
- comment/format 不影响 semantic identity；
- idempotent import；
- duplicate URL/target merge；
- invalid source 不污染 catalog；
- resolved snapshot hash；
- RSS fetch parity；
- Web source API parity；
- source toggle 不修改 YAML。

### 验收门禁

- flag 开启时当前 RSS pipeline 与现有 fixture parity。
- `config/sources.yml` byte-for-byte 不变。
- runner 和 ingestion 不再要求从固定 YAML path 读取 source。
- SourceCatalog 启用后不存在 YAML/SQLite 双写或 last-write-wins 语义。
- 关闭 flag 可立即回到旧路径。

## 11. M5：Connector contract、RSS/RSSHub 与 Inbox

### 目标

把“追踪对象”和“获取方式”分开，证明非 RSS-native SourceTarget 可以通过不同 binding 工作。

### 任务 A：Connector interface

实现：

```text
discover_capabilities(target)
validate(binding)
fetch(binding, cursor, limits)
health(binding)
normalize_provenance(raw_result)
```

统一 ConnectorResult、错误 taxonomy、rate limit、cursor、provenance 和 credential reference。

### 任务 B：RSSConnector 与 RSSHubConnector

1. 将当前 RSS fetch 逻辑适配到 `RSSConnector`。
2. `RSSHubConnector` 明确保存 route、instance、required credential refs 和 platform target identity。
3. Bilibili creator 等 SourceTarget 可绑定 RSSHub route，但 domain 不暴露为“RSS source”。
4. 保留部分来源失败语义和错误脱敏。

### 任务 C：InboxConnector

1. 新增用户分享入口：

   ```text
   POST /api/inbox/items
   GET  /api/inbox/items
   ```

2. 第一版接受 URL、标题、用户备注和可选捕获正文。
3. 解析 URL、metadata 和 source identity；获取失败时仍保存用户提供的最小 item。
4. Inbox item 进入 canonical ingestion，并带 `origin=user_shared` provenance。
5. 由 source resolver 尝试建立持续跟踪 binding；失败则保持 `unresolved`，不能声称已订阅。

### 主要测试

- connector contract conformance；
- RSS/RSSHub fixture parity；
- Bilibili creator target 与 RSSHub binding 分离；
- Inbox URL/content ingestion；
- 微信文章 unresolved fallback；
- credential 不进入 Agent input/trace；
- redirect、oversize、timeout 和 unsupported content type；
- connector partial failure 不覆盖其他成功来源。

### 验收门禁

- pipeline 不再以 `source_type == rss` 表达整个产品边界。
- RSS 和 Inbox 都能生成 canonical item。
- 持续追踪不可用时状态诚实、内容仍可进入系统。

## 12. M6：Source Discovery 与来源生命周期

### 目标

根据 EffectiveProfile 和用户分享内容自动发现、验证并维护新的 SourceTarget。

### 前置选择门

在正式编码真实 search adapter 前，评估并记录首个 SearchProvider：

- API/授权与成本；
- 中文与英文 source discovery 表现；
- structured result；
- 可测试/可录制；
- rate limit；
- 是否把用户画像发送给第三方；
- 本机 secret 管理。

SearchProvider 必须有 interface 和 FakeSearchProvider；具体供应商不能泄漏进 SourceDiscoveryAgent contract。

### 任务

1. 实现 deterministic `decide_source_discovery_due`：

   - profile hash 变化；
   - 显式 follow/share event；
   - 距上次 discovery 超过间隔；
   - active source health/coverage 下降。

2. Profile Compiler 生成 discovery hints，但不直接生成可执行 URL。
3. Source Discovery Agent 输出 typed candidate identity、URL、kind、rationale、query/event 和 confidence。
4. 本地 pipeline 执行：去重、域名 policy、connector resolution、probe、内容抽样、质量/重复检查。
5. 新来源默认 `probation`，使用较小抓取 quota。
6. 基于确定性 observation 实现 `probation -> active/paused/rejected/unhealthy/retired`。
7. Agent 不能跳过 validation、强制 active 或修改 connector credential。
8. 保存完整 search input/result、candidate、reject reason 和 lifecycle trace。

### 主要测试

- discovery cadence；
- profile change triggers；
- duplicate source convergence；
- malicious URL/private network/redirect rejection；
- fake source and low-content source；
- search result prompt injection；
- quantity reward hack；
- probation quota；
- source health decay/promotion/retirement；
- SearchProvider outage fallback；
- no secret in trace。

### 验收门禁

- Agent 输出不能直接成为 active source。
- 自动发现带来至少一个通过真实 connector validation 的来源，同时不会无上限增长。
- Search/Agent 失败时继续使用上一版 ResolvedSourceSnapshot。

## 13. M7：AgentAssessment 与 hybrid ranking

### 目标

让 Agent 智能判断进入新闻评分与优先队列，同时保持可复现基础层、证据和 fallback。

### 任务 A：重构现有 scorer

1. 保持现有 `build_signals.py` output parity，先拆出：

   ```text
   compute_baseline_assessment(item, profile, rules)
   build_candidate_pool(items, baseline, policy)
   compose_final_score(baseline, agent_assessment, policy)
   publish_ranked_signals(...)
   ```

2. 现有 `importance_score`、`relevance_score` 和排序在 Agent flag 关闭时完全不变。

### 任务 B：Candidate pool

组合：

- baseline high scorers；
- source-diverse sample；
- 新 entity/topic；
- pinned source；
- recent shared-source update；
- bounded exploration sample。

为每个入池原因记录 `candidate_reasons[]`。

### 任务 C：News Assessment Agent

1. Typed output 字段：relevance、novelty、credibility、urgency、counter_signal、reasoning_summary、evidence_spans。
2. 模型只看到 canonical item、EffectiveProfile 的必要字段和 assessment rubric。
3. 来源正文以 untrusted data 包裹，禁止继承其中指令。
4. verifier 检查 item ID、span 边界、引用文本、数值范围和 prohibited claims。
5. 使用 batch 或 staged reranker 前先做 spike；以成本、截断、排序稳定性和 eval 结果决定。

### 任务 D：Hybrid score

1. 权重写入版本化 policy，不由模型返回。
2. 同时保存 baseline component、Agent component、final score 和 policy version。
3. Agent invalid/timeout 时 item-level fallback；全部失败时 deterministic-only。
4. 保持 dashboard 现有字段，新增字段向后兼容。

### 主要测试

- baseline parity；
- evidence span validation；
- hallucinated citation rejection；
- all-high-score reward hack；
- source-name/文风 credibility shortcut；
- duplicate items；
- long/empty content；
- prompt injection；
- partial Agent failure；
- full fallback；
- score policy version；
- candidate recall fixture；
- ranking stability across recorded outputs。

### 验收门禁

- 每个发布 assessment 可回到 canonical evidence。
- Agent 不能直接设置 final score。
- Agent flag 关闭或模型不可用时，现有 deterministic output 仍有效。
- Eval 证明 Agent ranking 相比 baseline 有改善，且不是仅提高文案流畅度。

## 14. M8：L4Runner、API 与 Dashboard 接入

### 目标

把已验证的节点组成一条固定 workflow，并接入现有 refresh 与当前看板。

### 任务

1. 新增 `L4WorkflowRunner`，步骤固定为：

   ```text
   persist events
   -> compile/resolve profile
   -> decide/discover sources
   -> resolve source snapshot
   -> collect
   -> ingest/store
   -> baseline score
   -> Agent assess
   -> validate/compose
   -> publish
   -> trace
   ```

2. 复用现有 `PipelineRunner` 的 lock、status、tmp dir、安全 publish 和 failure preservation；禁止创建第二套 refresh lifecycle。
3. 扩展 refresh status：

   ```text
   workflow_run_id
   profile_id
   source_snapshot_id
   current_step
   step_results
   agent_stage_status
   degraded_reasons
   cost/usage summary
   ```

4. Web `/api/refresh` 与 Agent `run_refresh_pipeline` 继续进入同一 runner。
5. 更新用户界面：

   - 当前信息输入；
   - profile initialized/updated status；
   - Inbox share；
   - SourceTarget follow/unfollow 与 tracking state；
   - score provenance；
   - Agent degraded indicator。

6. 不改变主页面的新闻卡与三栏信息架构。
7. 长任务先使用现有同步 refresh 语义；如真实运行已不可接受，再单独设计 background job，不在本阶段顺带引入 LangGraph。

### 主要测试

- full fixture workflow；
- exact step order；
- lock/concurrent refresh；
- profile/source/Agent step failures；
- partial connector success；
- safe publish；
- Web/Agent runner identity；
- API same-origin；
- UI error/degraded states；
- current dashboard compatibility；
- refresh status trace linkage。

### 验收门禁

- 所有用户可见能力进入真实后端，不使用前端 mock。
- 任意 Agent 节点失败时仍有明确、可验证的 fallback。
- 用户可以从输入 context 到看到 hybrid-ranked 新闻完成一条真实闭环。

## 15. M9：Run Inspector、最终 eval、数据迁移与默认切换

### 目标

完成开发者控制面、数据迁移、默认启用、文档修正和最终 pressure test。

### 任务 A：Developer Run Inspector

提供本机开发者视图：

- workflow run 列表与 step timeline；
- UserContextEvent 与 ProfileSnapshot provenance；
- source candidate、validation、binding 和 lifecycle；
- baseline/Agent/final score；
- model、prompt、policy、schema version；
- tool/connector call；
- usage、retry、error 和 degraded reason；
- replay 按钮或 CLI；
- rollback active profile/source snapshot；
- per-stage kill switch。

不展示 raw chain-of-thought。

### 任务 B：数据迁移与默认切换

1. 备份并 semantic import 当前 `sources.yml`。
2. 不自动导入硬编码 `user-profile.yml` 为真实用户。
3. 把 `user-profile.yml` 改为 example/legacy compatibility，更新 UI 与 docs。
4. SourceCatalog 和 ProfileStore 通过验收后改为默认路径。
5. 保留一个发布周期的 YAML/profile compatibility adapter 与显式 fallback flag。
6. 只有在 rollback smoke 通过后才删除失效的数据兼容代码；Agent runtime 已在 M1 完成 PydanticAI 单路径切换。

### 任务 C：最终评测

1. 全量自动测试。
2. Pydantic Evals 或等价 code-first eval：

   - Profile Compiler；
   - Source Discovery；
   - News Assessment；
   - span/trace behavior。

3. 使用录制 fixture 做多模型/多 prompt regression。
4. 可选真实 smoke：RSSHub、真实 provider、Bilibili creator target、Inbox URL。
5. 检查成本、运行时长、source 增长、failure rate 和 fallback rate。
6. 重新 pressure test，覆盖：

   - 测评未覆盖路径；
   - reward hack；
   - 需求理解偏差；
   - prompt injection；
   - 画像过度推断；
   - 来源数量膨胀；
   - 数据迁移/回滚；
   - framework lock-in；
   - maintainability。

7. 如发现漏洞，先形成漏洞清单和改进方案，经用户确认后修改并重新测试/pressure test。

### 任务 D：文档修正

至少更新：

```text
docs/index.md
docs/current-demo-architecture.md
docs/agent-core/index.md
docs/fetcher-adapters.md
docs/ingestion.md
docs/signal-processing.md
docs/storage.md
docs/web-app/architecture.md
docs/agent-roadmap/l3-l4-l5-roadmap.md
```

旧 roadmap 中的 Ruby 和末端 briefing 描述必须改为历史记录或归档，不能继续作为 current truth。

### 最终门禁

```bash
uv run --extra dev pytest -q
git diff --check
```

可选真实 smoke 不替代自动测试。没有 API key 或网络时，自动测试仍必须完整通过。

## 16. 测试分层

### T1：纯 domain/unit

- schema、enum、hash、policy、score composition；
- 无数据库、无网络、无模型。

### T2：Repository/integration

- in-memory/temp SQLite；
- migration、transaction、idempotency、rollback。

### T3：Agent recorded/fake

- PydanticAI test/fake model；
- typed output、retry、budget、trace、reward-hack fixture；
- 不调用真实 provider。

### T4：Pipeline fixture

- fake connector + canonical fixtures；
- 完整 L4 workflow、fallback 和 publish。

### T5：HTTP/browser

- FastAPI TestClient；
- dashboard、context input、Inbox、source state、score provenance；
- 真实浏览器 smoke 在自动 API 测试后执行。

### T6：Optional real smoke

- Docker/RSSHub；
- 真实 SearchProvider；
- 真实 LLM provider；
- 真实公开 URL。

## 17. Reward-hack 防护矩阵

| 节点 | 可能的假成功 | 必须的反制 |
| --- | --- | --- |
| Profile Compiler | 填满字段看似懂用户 | provenance、unknown preservation、显式纠错优先、TTL |
| Source Discovery | 找到大量来源即算成功 | downstream useful-item yield、quota、dedupe、probation |
| Connector | HTTP 200 即算可用 | 内容解析、更新性、重复率、provenance、health history |
| Candidate pool | 只评估 baseline Top N | exploration bucket、recall fixture、source diversity |
| News Assessment | 所有新闻都给高分 | 分布检查、negative cases、calibration、固定 final formula |
| Evidence | 引用标题就算 grounding | span 边界、claim coverage、正文/metadata distinction |
| Audit | 有日志文件即算可审计 | run linkage、input/output hashes、policy/model versions、replay |
| Fallback | 返回旧数据但声称当前成功 | generated_at/run_id/status 必须一致并显式 degraded |

## 18. 发布与回滚策略

### 发布

- 所有新路径先 behind feature flags。
- 先在 fixture/temp DB 运行，再在当前本机数据副本运行。
- SourceCatalog import 使用 dry-run summary 后再 commit transaction。
- 默认切换顺序：ProfileStore -> SourceCatalog -> Inbox/Discovery -> Agent Ranking -> L4Runner。
- 每次只切换一个 source of truth。

### 回滚

- flags 可将 profile、source 和 ranking 独立切回旧路径。
- 不删除原 YAML，直到 catalog 默认运行稳定且 migration rollback 通过。
- ProfileSnapshot 与 SourceSnapshot immutable，可切回上一 active pointer。
- signals 继续使用 temp + atomic replace。
- 数据库 migration 不做 destructive downgrade；回滚 application code 时保留新表。

## 19. 建议提交边界

```text
1. docs: add L4 evaluation plan and acceptance matrix
2. feat: add PydanticAI runtime compatibility spike
3. feat: add L4 domain contracts and SQLite repositories
4. feat: add user context events and profile compiler
5. feat: add source catalog and YAML seed migration
6. refactor: route RSS pipeline through source snapshots
7. feat: add connector contract and inbox ingestion
8. feat: add bounded source discovery and lifecycle
9. refactor: split deterministic baseline scoring
10. feat: add Agent assessments and hybrid ranking
11. feat: compose fixed L4 workflow and APIs
12. feat: add dashboard L4 controls and developer inspector
13. docs: update current architecture and archive stale roadmap
14. test: final eval and pressure-test hardening
```

每个提交必须可独立测试。禁止把数据库迁移、框架替换和 UI 改造塞进同一不可审查提交。

## 20. 开始编码前必须锁定的决策

以下决策会改变实现或评测，必须在对应 milestone 开始前锁定：

1. M0：L4 evaluation plan 是否覆盖完整需求，用户是否认可验收口径。
2. M1：已锁定 PydanticAI 作为唯一 Agent runtime，并删除自建 loop。
3. M3：ProfileSnapshot 字段、显式/推断 precedence 和 TTL policy。
4. M6：首个 SearchProvider 及隐私/成本边界。
5. M7：per-item、batch 或 staged reranker；hybrid score calibration 方法。
6. M9：默认切换条件、compatibility adapter 保留周期和 implicit behavior retention。

不需要提前锁定第一个 HTML/Browser connector；L4 beta 先用 RSS/RSSHub + Inbox 证明 domain 解耦和真实闭环。

## 21. L4 开发完成条件

只有同时满足以下条件才可声明 L4 完成：

- 用户真实 context 是画像输入，硬编码 profile 不再静默生效；
- 自动画像更新无需用户审批，但开发者可以 inspect、configure、replay 和 rollback；
- SourceCatalog 是动态 source truth，YAML 只作 seed/compatibility；
- SourceTarget 与 AcquisitionBinding 解耦；
- 至少 RSS/RSSHub 和 Inbox 两类 connector 进入真实主线；
- Source Discovery 能产生经验证、受 quota 管理的 source；
- AgentAssessment 进入最终新闻排序，并有 canonical evidence；
- Agent、Search 或 connector 失败时能安全降级；
- Web 与 Agent 使用同一 L4 runner；
- 当前新闻 dashboard 继续可用；
- 所有 Agent 行为可追溯到 model、prompt、policy、tool、evidence 和 workflow run；
- 自动测试、eval、迁移测试、回滚 smoke 和最终 pressure test 全部通过；
- 当前架构文档已更新，旧实现描述不再冒充 current truth。
