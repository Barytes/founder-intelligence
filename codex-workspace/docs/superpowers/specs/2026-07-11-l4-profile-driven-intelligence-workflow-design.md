# L4 画像驱动情报工作流需求设计

日期：2026-07-11

状态：待用户评审。本文件记录目前已经形成的需求与设计方向，不是最终实现方案；实施前仍需补充独立的实现方案和可执行测评方案。

## 1. 文档目的

将 Founder Intelligence 的 L4 定义为一条固定、可审计的 Agent 工作流：从真实用户信息出发，动态维护用户画像和信息源，通过多种 connector 获取内容，在确定性处理基础上加入 Agent 智能评分，最后继续以当前的新闻优先队列呈现。

```text
用户信息
-> 有效用户画像
-> 信息源发现与维护
-> 多 connector 抓取
-> canonical content
-> 确定性基础评分
-> Agent 评估与重排
-> 当前新闻看板
```

L4 的任务是提高现有情报 workflow 的智能程度，不在此阶段决定产品最终交互形态。当前新闻卡片、分数、优先队列、来源详情和原始链接仍是主要用户界面。

长期愿景保持不变：让创业者拥有接近咨询公司、投行研究部门的信息能力和决策能力。L4 是下一层 runtime，不是最终产品形态。

## 2. 当前代码基线

当前 checkout 已经不是旧文档中的 Ruby pipeline 加 sidecar Agent：

- FastAPI 是统一的本机 HTTP 后端。
- Web 刷新与 Agent 的 `run_refresh_pipeline` 共用 `agentic_core.pipeline.runner.PipelineRunner`。
- Python 主流程为 `fetch_rss -> ingest_adapter_output -> store_canonical_jsonl -> build_signals -> publish`。
- `config/sources.yml` 是唯一实际 source registry。
- `config/user-profile.yml` 被直接传给 `build_signals`，充当当前有效画像。
- `build_signals.py` 以确定性规则计算重要性、相关性、总分、解释、风险和排序。
- `AgenticCore` 已切换为 PydanticAI 单一 runtime，通过兼容 facade 保留 `RunResult`、工具权限和 Web/CLI 合同；自建 provider 与 Agent loop 已删除。
- 当前只有 enabled RSS source 能进入真实 fetch path。

与 L4 相关的现存问题：

1. `config/user-profile.yml` 中为开发方便写死的示例人物，被当成真实用户 source of truth。
2. `config/sources.yml` 同时承担人工配置和动态状态；页面操作会重序列化整个 YAML，产生格式噪声，不适合 Agent 高频更新。
3. “信息源”和“获取协议”被混为一体。Bilibili UP 主、微信公众号是产品层 source；RSS、RSSHub、API、HTML、Browser 或 Inbox 才是获取方式。
4. 确定性评分只能处理已配置的词、标签和权重，无法可靠判断语义相关性、新颖性、可信度和意外重要性。
5. PydanticAI runtime 已提供 typed output retry、provider 适配、预算和 trace 基础；L4 后续节点仍需各自的 schema、policy、eval 和持久化 trace。

## 3. 已确认的产品与架构决策

### D1. 用户事实是 source of truth

`config/user-profile.yml` 不再代表真实用户。可以沿用其字段思路，但不能把其中的写死内容作为默认画像。

权威输入是 append-only 的用户信息事件；有效画像是 Agent 对这些事件生成的、带版本和来源的派生视图。

### D2. 用户不需要审批每次画像 diff

画像更新经本地 schema 与 policy 验证后自动生效，正常用户流程不弹出逐字段审批。

开发者必须能够查看输入、输出、字段来源、模型、prompt、policy、验证结果和状态变化，并能重放、修改策略、禁用或回滚。

### D3. 自动发现和维护信息源属于 L4

系统使用有效画像和用户平时分享、阅读、保存的内容，自动发现 Source Target，验证获取方式，并管理新增、观察、启用、暂停和淘汰。

### D4. RSS 是 connector，不是产品边界

RSS 仍是第一种、也是成本最低的 connector，但 L4 数据模型必须容纳 RSSHub、官方 API、HTML、Browser、MCP 和用户分享 Inbox。

### D5. Agent 参与评分与优先队列

保留确定性评分作为可复现基础分和故障 fallback；Agent 增加语义相关性、新颖性、可信度、紧迫性、反向信号和证据解释；最终队列使用受控 hybrid score。

### D6. L4 仍是固定 workflow

步骤顺序、预算、重试、允许的状态变化、connector policy、评分合成、验证和降级均由系统控制。Agent 只在具名节点内做有限判断，不能自行规划或改变 workflow 拓扑。

### D7. 选择性引入 Agent 框架

PydanticAI 已替换自建的 provider/tool/output 循环，承担类型化 Agent 节点、模型适配、工具、重试、使用限制、事件、trace 和 eval 接入。

不让框架接管 `PipelineRunner`、canonical contract、connector、repository、确定性验证和评分 policy。

L4 不采用 LangChain `create_agent` 作为主架构。出现跨进程 checkpoint、长时间暂停、分布式 worker 或可恢复后台任务时，再评估 LangGraph 或 PydanticAI durable-execution integration。

## 4. 目标

### G1. 从真实用户信息生成有效画像

系统接收用户主动输入和行为证据，自动生成结构化画像，并随用户状态变化更新。

### G2. 自动扩展和维护来源

系统根据画像发现相关 source identity，解析可用 acquisition method，验证并管理其生命周期，无需用户手工编辑 YAML。

### G3. 支持非 RSS-native 内容

用户分享文章、视频、创作者主页、公众号文章、仓库或网站后，系统能够识别对应公开 Source Target；在技术和合规允许时建立持续追踪，不能持续追踪时保留 Inbox 获取路径。

### G4. Agent 参与新闻判断和排序

Agent 贡献语义判断，同时保留基础分、证据、评分合成过程和确定性 fallback。

### G5. 保持当前新闻呈现形式

L4 继续使用新闻卡片、分数、详情、来源和原链接。决策桌面、认知差分等未来交互不在本需求范围。

### G6. Agent 行为可理解、可审计、可控制

开发者能够回答 Agent 看到了什么、输出了什么、改变了什么、为什么改变、最终发布了什么；能够修改版本化 policy、prompt、schema 和模型，并重放和对比历史运行。

## 5. 非目标

L4 不包括：

- 完全自主的 observe-plan-act-reflect controller；
- 任意 shell 或任意网络访问；
- 由模型决定 workflow 拓扑或最终评分公式；
- 要求用户审批正常画像和来源 diff；
- 重做最终产品交互；
- 根据新闻自动执行外部业务行动；
- 保证访问私有、登录态或平台限制内容；
- 向 LLM 暴露 token、cookie、credential 或私有浏览器状态；
- 把 LLM 自己生成的解释当作证据；
- 删除确定性抓取、标准化、验证和降级路径。

## 6. 用户与关键场景

### 主要用户

需要持续获得与当前项目、决策、假设、竞争、技术和市场相关公开信息的创业者或研究型用户。

### 开发者/运维者

负责模型、prompt、workflow policy、connector 权限、预算、schema、eval dataset 和恢复策略的本机开发者。

### 场景 A：首次输入用户信息

1. 用户用自然语言描述当前工作、目标、阶段、开放问题、关注点、排除项和观察对象。
2. Profile Compiler 生成并自动启用通过验证的 Profile Snapshot。
3. Source Discovery 寻找相关 Source Target 和 acquisition option。
4. pipeline 抓取、评估并排序内容。
5. 看板基于真实用户信息呈现，而不是使用旧的写死 founder 画像。

### 场景 B：用户重点发生变化

1. 用户说明旧主题不再重要，或提出新项目、新问题。
2. 系统保存新的 UserContextEvent。
3. Profile Compiler 更新目标、主题权重、排除项、观察实体和 TTL。
4. Source Discovery 调整来源组合。
5. 下一次运行记录实际使用的 profile version。

### 场景 C：用户分享 Bilibili 视频

1. 用户分享公开的视频 URL 或 UP 主主页。
2. 系统将分享行为保存为用户证据，并识别 UP 主为 SourceTarget。
3. ConnectorResolver 尝试 RSSHub、公开 API 或合规页面 connector。
4. 通过验证后，该来源进入 probation，后续公开更新被抓取。
5. 若没有稳定 binding，分享内容仍进入 Inbox，但系统不能假装已开启持续追踪。

### 场景 D：用户分享微信公众号文章

1. 文章以 URL 或捕获文档进入 Inbox。
2. 系统尽可能识别公众号身份并建立 SourceTarget。
3. ConnectorResolver 尝试允许的获取方式。
4. 如果无法稳定自动追踪，则状态为 `unresolved`；用户后续分享的文章仍可继续进入系统。

### 场景 E：Agent 评分失败

1. 抓取和 canonical ingestion 成功。
2. News Assessment Agent 超时、超预算或给出无效证据引用。
3. 无效 assessment 不发布。
4. 系统以 `agent_status: degraded` 发布确定性优先队列。
5. 上一次成功的 Agent assessment 仅供审计，不能冒充当前结果。

## 7. 概念数据模型

### 7.1 UserContextEvent

不可变的用户事实或行为证据。

```text
event_id
user_id
event_type
occurred_at
captured_at
payload
origin
explicitness
confidence
supersedes_event_ids[]
```

建议的 event type：

- `user_statement`
- `goal_update`
- `shared_content`
- `saved_signal`
- `dismissed_signal`
- `source_follow_request`
- `source_unfollow_request`
- `profile_correction`

显式陈述和纠错优先于被动行为推断；未知信息保持未知，不能被自动补成确定事实。

### 7.2 ProfileSnapshot

供下游使用的版本化 Agent 派生画像。

```text
profile_id
user_id
schema_version
created_at
based_on_event_ids[]
active_goals[]
interests[]
watch_entities[]
negative_preferences[]
open_questions[]
output_preferences
field_provenance
field_confidence
field_expires_at
model_id
prompt_version
policy_version
validation_status
```

ProfileSnapshot 不得覆盖底层用户事件。

### 7.3 EffectiveProfile

一次 workflow run 实际使用的不可变画像，由 active ProfileSnapshot 与开发者 policy default 合并产生。每次运行保存 `profile_id` 和内容 hash。

不存在有效画像时，个性化相关性评分不可用；UI 必须明确显示未初始化，不能 fallback 到仓库内的虚构用户。

### 7.4 SourceTarget

描述用户想追踪“什么”，与“怎样获取”无关。

示例：Bilibili UP 主、微信公众号、GitHub 仓库或组织、网站作者、newsletter、主题查询、手工固定 feed。

```text
source_target_id
source_kind
canonical_identity
display_name
canonical_url
discovered_from
relevance_to_profile
status
created_at
updated_at
```

### 7.5 AcquisitionBinding

描述获取 SourceTarget 更新的一种方式。

```text
binding_id
source_target_id
connector_type
connector_config_ref
public_or_authenticated
status
health_score
last_success_at
last_failure_at
failure_class
rate_limit_policy
credential_ref
```

由 policy 控制的 connector type：

```text
rss
rsshub
api
html
browser
mcp
inbox
```

凭证只以 opaque reference 存在，并只注入 connector execution；不能进入 Agent prompt、trace 或 artifact。

### 7.6 ResolvedSourceSnapshot

一次运行的不可变 source 输入，由 active SourceTarget、健康 AcquisitionBinding、quota 和 policy 解析产生。它将替代 runner 对 `config/sources.yml` 的直接依赖。

### 7.7 AgentAssessment

Agent 对一个 canonical item 的结构化语义判断。

```text
assessment_id
item_id
profile_id
agent_relevance
novelty
credibility
urgency
counter_signal
reasoning_summary
evidence_spans[]
model_id
prompt_version
policy_version
usage
validation_status
```

每个 evidence span 必须指向 canonical item 或 source metadata 中真实存在的内容。

### 7.8 RankedSignal

在当前 signal contract 上增加评分来源：

```text
deterministic_importance_score
deterministic_relevance_score
agent_assessment
final_score
score_policy_version
agent_status
```

最终分数由开发者 policy 在代码中计算；模型不直接选择权重或绕过 assessment schema 决定最终排序。

## 8. 存储要求

本机单用户 L4 推荐使用 SQLite 保存可变、关联型 runtime state：

```text
user_context_events
profile_snapshots
source_targets
acquisition_bindings
source_discovery_events
source_health_runs
workflow_runs
agent_assessments
```

现有 append-only canonical JSONL 可在 L4 继续承担内容历史。视频等大型二进制内容不写入 SQLite，只保存 metadata 和 content reference。

Committed YAML 只承载开发者 policy、example 和 bootstrap seed：

```text
config/user-profile.example.yml
config/sources.yml                 # 迁移期 seed
config/workflow-policy.yml         # 未来开发者 policy
config/signal-rules.yml            # 确定性和 hybrid score policy
config/ingestion-rules.yml
```

长期可保留 `sources.example.yml` 作为 fixture、导入导出和紧急 bootstrap，但不能继续作为动态 runtime registry。

## 9. L4 固定工作流

```text
触发：用户信息更新或 refresh 请求

1. persist_user_context_events
2. compile_profile
3. validate_and_activate_profile
4. decide_source_discovery_due        # 确定性 policy
5. discover_source_targets            # 有界 Agent 节点
6. resolve_connector_candidates       # 代码 + 有界 Agent 分类
7. probe_and_validate_bindings         # 确定性 connector 执行
8. update_source_catalog
9. build_resolved_source_snapshot
10. collect_content                    # 多 connector
11. normalize_to_canonical_items
12. append_content_and_run_records
13. compute_deterministic_scores
14. build_assessment_candidate_pool
15. assess_candidates                  # 有界 Agent 节点
16. validate_assessments
17. compose_hybrid_scores              # 确定性 policy
18. publish_latest_signals
19. write_workflow_trace
```

步骤顺序固定。是否执行 source discovery 由画像变化、时间间隔、显式 follow 请求和 connector health 等确定性条件决定，不由 open-ended planner 决定。

## 10. Profile Compiler 需求

### 功能需求

- 输入一组 UserContextEvent 和上一版 ProfileSnapshot。
- 输出完整 typed ProfileSnapshot，而非自由文本或任意 patch。
- 遵守显式 supersession 和 correction。
- 保留未知和不确定字段。
- 为推断出的临时兴趣、目标增加 TTL。
- 不能仅凭被动行为删除用户明确表达的长期偏好。
- 通过 schema 和 policy 验证后自动生效。
- 保存 input event IDs、model、prompt、policy、output、验证结果和 usage。

### 开发者控制

- 节点启停；
- 可写 profile field；
- merge 与 supersession policy；
- 显式信息和推断信息优先级；
- confidence threshold；
- TTL default；
- model 与 prompt version；
- request/token/tool budget；
- fallback；
- recorded-output replay；
- 回滚 active ProfileSnapshot。

## 11. Source Discovery 与 Connector 需求

### Source discovery

Source Discovery Agent 根据 EffectiveProfile 与用户分享内容生成有数量限制的 search intent。每个候选必须包含：

```text
candidate identity
candidate URL
source kind
profile rationale
discovery query/event
expected content type
confidence
```

Agent 不能直接激活任意 URL；候选必须通过 connector resolution 和程序验证。

### Connector resolution

ConnectorResolver 依据明确 policy 选择获取方式，例如：

```text
原生 RSS/Atom
-> 可信 RSSHub route
-> 官方/公开 API
-> approved HTML connector
-> approved browser/MCP connector
-> inbox-only fallback
```

优先级是 policy，不是 LLM 决策。Agent 可以辅助识别页面与 source identity，但 binding 必须由代码验证。

### Source 生命周期

```text
candidate
probation
active
paused
unhealthy
unresolved
rejected
retired
```

Probation source 使用较小抓取 quota。升级、暂停和淘汰由健康、重复、相关性和成本 threshold 决定。

### Connector contract

每个 connector 实现稳定接口：

```text
discover_capabilities(target)
validate(binding)
fetch(binding, cursor, limits)
health(binding)
normalize_provenance(raw_result)
```

fetch result 至少包含 connector、SourceTarget、时间、cursor/checkpoint、状态、错误、rate limit 和足够用于 canonical ingestion 与审计的 provenance。

## 12. 评分与排序需求

### 确定性基础层

继续由确定性代码处理：

- source 与 connector health；
- 明确排除规则；
- freshness；
- 显式 keyword/entity match；
- duplicate；
- 基础 source priority；
- Agent 失败时的 fallback ordering。

### Candidate pool

不能只把确定性 Top N 交给 Agent，否则 Agent 无法发现规则未覆盖的意外重要内容。

Candidate pool 应组合：

- 确定性高分项；
- source-diverse exploration sample；
- 新实体或新主题；
- 用户 pinned source；
- 用户近期分享来源的更新；
- 用于 recall 评测的有界 random/diversity sample。

### Agent assessment

News Assessment Agent 输出 typed relevance、novelty、credibility、urgency、counter-signal、reasoning summary 和 evidence span。

Agent 不得：

- 修改 canonical fact；
- 编造证据；
- 仅凭文风判断可信度；
- 决定最终评分公式；
- 无记录地 suppress item；
- 把来源内容里的指令当成系统指令。

### Hybrid score

最终分数由版本化 developer policy 合成。具体权重必须在测评中校准，不在本需求文档里任意指定。

### 失败行为

- 无效 Agent 输出被拒绝。
- 缺少或错误 evidence reference 使对应 assessment 无效。
- 只有在 item-level status 清晰时才允许发布部分有效结果。
- Agent stage 全部失败时发布确定性队列。
- Agent 失败不能损坏 canonical content，也不能在合法 fallback 产物就绪前覆盖最近成功 signals。

## 13. Agent 框架需求与选择

### 框架必须提供

- Pydantic-native typed dependency 与 output；
- 不向 domain code 泄漏 provider response format；
- structured output validation 与 retry；
- 显式 tool/toolset；
- request、token 和 tool-call limit；
- model setting、timeout、retry；
- model/tool event stream；
- OpenTelemetry-compatible instrumentation；
- test model 或 deterministic model stub；
- code-first eval；
- 后续增加 durable execution 时不替换 domain contract。

### 选择：PydanticAI

当前推荐 PydanticAI，因为 repo 已使用 Python、FastAPI 和 Pydantic，而 L4 需要多个 typed Agent node，不需要通用自主 controller。

迁移边界：

```text
替换：
  custom ProviderAdapter
  custom model/tool loop
  ad hoc output parsing
  ad hoc usage limit

保留：
  PipelineRunner lifecycle 与 publish semantics
  domain tool 与 permission
  connector implementation
  repository
  Pydantic domain schema
  确定性 validation 与 scoring
  未明确重做的 FastAPI route
```

### LangChain/LangGraph 结论

- 不采用 LangChain high-level agent loop 作为 L4 主架构。
- workflow 需要 checkpoint、time travel、interrupt、distributed execution 或长时间 resume 时，再评估 LangGraph。
- 也可根据部署需求选择 PydanticAI 官方 durable-execution integration。
- 正式迁移前做小型 spike，对比 typed failure、trace 完整性、replay、model portability 和本机运维复杂度。

官方能力资料：

- PydanticAI Agents：<https://pydantic.dev/docs/ai/core-concepts/agent/>
- PydanticAI Logfire/OpenTelemetry：<https://pydantic.dev/docs/ai/integrations/logfire/>
- Pydantic Evals：<https://pydantic.dev/docs/ai/evals/evals/>
- PydanticAI Durable Execution：<https://pydantic.dev/docs/ai/integrations/durable_execution/overview/>
- LangChain Agents：<https://docs.langchain.com/oss/python/langchain/agents>
- LangGraph Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>

## 14. 可观测、审计与控制

每次运行有稳定 `workflow_run_id`，append-only trace 至少包含：

```text
trigger 与 user event IDs
workflow version
step name 与 status
input/output artifact IDs 和 hashes
profile/source snapshot IDs
model 与 provider
prompt 与 policy version
tool call 与 validated arguments
connector call 与 status
token/request/tool usage
retry 与 error
validation decision
score composition
fallback/degradation decision
publish result
```

开发者控制必须包括：

- 每个 Agent stage 独立启停；
- 每个 Agent stage 的 model；
- prompt/schema version；
- source discovery cadence 与 quota；
- connector allowlist 与 credential policy；
- profile field allowlist 与 TTL policy；
- assessment candidate/cost limit；
- score policy version；
- deterministic-only mode；
- recorded-output replay；
- connector 支持时的 run cancellation；
- active profile/source snapshot rollback。

审计不要求保存 raw chain-of-thought。结构化 input、output、evidence、decision、tool call、policy 和状态变化才是可验证依据。

## 15. 安全与完整性

- Workbench 默认继续只绑定 loopback。
- LLM 不接收 secret、cookie、token 或未脱敏 credential reference。
- 抓取内容均视为 untrusted data，不能改变 tool permission 或 workflow instruction。
- 即使 provider 支持 structured output，也必须在本地再次验证。
- Source discovery 不能把任意 URL 变成任意命令执行入口。
- HTML/Browser connector 必须有 domain、network、size、timeout、redirect 和 content-type policy。
- 私有/登录 connector 需要用户显式配置，并隔离注入 credential。
- Source 新增、状态变化和评分变化都能追溯到 workflow run。
- Profile、source、assessment 更新失败时保留上一版有效 snapshot。

## 16. 用户界面需求

L4 保留当前 dashboard 信息架构，只做必要变化：

- 用自然语言“当前信息”入口替代 raw `user-profile.yml` 作为主要产品输入；
- 展示画像是否初始化及最近更新时间；
- 展示 source discovery/collection 状态，但不把 developer trace 噪声暴露给用户；
- 继续显示排序后的新闻卡和原链接；
- 在详情中显示确定性贡献、Agent 贡献和 degraded 状态；
- 支持用户向 Inbox 分享 URL/content；
- 支持对已识别 SourceTarget 显式 follow/unfollow；
- 无法追踪时明确显示 unresolved。

开发者 trace 放在 Agent/settings workbench 或单独 Run Inspector，不进入主看板。

## 17. Source-of-truth 规则

| 领域 | Runtime source of truth | Committed config 的作用 |
| --- | --- | --- |
| 用户事实 | UserContextEvent store | schema/example |
| 有效画像 | active ProfileSnapshot | policy default |
| Source identity | SourceCatalog | seed/import example |
| 获取状态 | AcquisitionBinding + health history | connector policy |
| Canonical content | canonical store | ingestion policy |
| Agent 判断 | assessment store + workflow trace | prompt/schema/policy version |
| 最终评分 | RankedSignal + score policy version | scoring policy |

任何 committed example content 都不能静默成为用户特定 runtime truth。

## 18. 迁移阶段

### Phase 0：修正 contract

- 定义 UserContextEvent、ProfileSnapshot、SourceTarget、AcquisitionBinding、AgentAssessment 和 trace schema。
- 将当前 `config/user-profile.yml` 标为开发 fixture，不再定义产品真相。
- 引入 repository interface，逐步解除 pipeline 对 YAML path 的直接依赖。
- 先加测试，再用 adapter 保持现有行为。

### Phase 1：画像驱动的 RSS workflow

- 增加真实用户信息输入与 event storage。
- 用 active ProfileSnapshot 替换写死 profile。
- 引入 PydanticAI Profile Compiler。
- 暂时保留现有 RSS sources 和确定性评分。
- 验证自动更新、trace、replay 与 fallback。

### Phase 2：动态 SourceCatalog

- 增加 SQLite SourceCatalog，将当前 YAML source 作为 seed 导入。
- 为现有 RSS/RSSHub fetch 生成 ResolvedSourceSnapshot。
- runner/ingestion 停止直接读取 `config/sources.yml`。
- 增加 source health、probation 和生命周期。
- 保留 YAML import/export。

### Phase 3：Agent Source Discovery

- 增加有界 search/discovery capability。
- 增加 Source Discovery Agent 和 ConnectorResolver。
- 自动管理新发现的 RSS/RSSHub binding。
- 扩展 connector 前先完成 discovery/source quality eval。

### Phase 4：Agent 辅助排序

- 构造包含 exploration 的 candidate pool。
- 增加 PydanticAI News Assessment Agent。
- 验证 evidence span 并计算 hybrid score。
- 保留 deterministic fallback 和当前 dashboard。

### Phase 5：非 RSS connector

- 优先增加 InboxConnector，使用户分享内容在无法持续追踪时仍可工作。
- 根据真实用户场景逐个增加 connector。
- 推荐验证顺序：native RSS/RSSHub target resolution、Inbox、公开 API、受限 HTML，最后才是 Browser/MCP。
- connector 产生长任务或跨进程恢复需求时，再评估 durable workflow runtime。

## 19. 测评与验收要求

本节定义 L4 验收意图；编码前必须另写可执行测评方案。

### 画像验收

- 没有真实用户信息时不得生成虚构个性化画像。
- 显式 correction 覆盖先前 inference。
- 每个 active field 有 provenance、confidence、policy/model/prompt version。
- 能用 recorded model output 重放 profile update。
- 无效输出不改变上一版 active profile。

### Source 验收

- Agent candidate 未通过 connector 验证不能进入 active run。
- 同一 source identity 去重为一个 SourceTarget，可有多个 binding。
- 用户分享 Bilibili 内容后，可建立独立于具体 transport 的 creator SourceTarget。
- 无法稳定追踪的微信公众号明确标为 unresolved。
- Source health 和 lifecycle 能从 observation 与 policy 复现。

### 评分验收

- 每个 AgentAssessment 指向 canonical item 和真实 evidence span。
- 模型不能直接决定最终权重。
- Agent 失败时发布合法确定性 fallback。
- Candidate-pool eval 同时测 recall，不能只测确定性 Top N precision。
- Golden dataset 包括相关、无关、新颖、重复、炒作、prompt injection 和 low-context 内容。
- 测评能发现“全部高分”“只引用标题”“只选择规则已高分项”等 reward hack。

### 审计验收

- 开发者能回答：改变了什么、为何改变、依据什么、使用哪个 model/prompt/policy、调用哪些 tool/connector、最终发布什么。
- 提供 recorded output 时可重放而不重复外部模型和 connector 调用。
- trace 中不存在 secret 或 raw credential。
- Profile、source 和 signal publication 关联同一 workflow run。

### 兼容验收

- 现有 canonical item contract 仍可读取。
- Web 与 Agent refresh 继续共享一个 workflow runner boundary。
- 失败运行保留最近成功 signals。
- 迁移期间当前 dashboard 持续可用。
- 当前 `config/sources.yml` 中的用户修改被保留并以非破坏方式导入。

## 20. 实施前 Pressure Test 风险

### R1. Profile inference 变成隐性监控

区分显式与行为事件，保留 provenance，对 inference 使用 TTL，并提供用户可见的纠错和删除能力；不需要逐次审批不等于用户无法控制。

### R2. Source Discovery 奖励数量而非质量

使用 quota、probation、duplicate clustering、health、relevance decay、collection cost budget；eval 以产生的有用内容衡量，不以发现 source 数量衡量。

### R3. 确定性预筛选遮蔽 unknown unknown

加入 source-diverse exploration 和 recall eval，不能只 rerank 规则 Top N。

### R4. Hybrid score 无法解释

保存各分量、policy version、item-level status 和 evidence；最终合成始终是确定性代码。

### R5. 框架反向拥有领域架构

PydanticAI 位于 Agent-node interface 后；pipeline、repository、connector、schema 和 policy 保持 framework-independent。

### R6. 非 RSS connector 变成脆弱爬虫工程

只为已验证场景增加 connector，优先稳定公开方式，记录 failure taxonomy，执行平台 policy，并始终保留 Inbox fallback。

### R7. YAML 迁移丢失用户修改

保留当前文件，使用 idempotent import，比较 semantic record 而非格式，停用 YAML runtime read 前必须通过迁移测试。

## 21. 实现方案阶段仍需锁定的决策

1. SQLite 具体 schema、repository API 和 migration tool。
2. ProfileSnapshot 字段体系和 event precedence matrix。
3. Source Discovery 使用的 search provider/tool。
4. Inbox 之后第一个非 RSS connector。
5. Hybrid score 权重和校准方法。
6. AgentAssessment 是 per-item、batch 还是 staged reranker。
7. 早期 trace 使用本地 OpenTelemetry、JSON artifact 或两者兼用。
8. 何时引入 LangGraph 或 durable-execution runtime。
9. 用户行为事件的数据保留与删除语义。
10. 如何向用户展示和纠正 implicit behavior inference。

这些决策必须在实现方案与测评方案中解决，不能由编码过程临时决定。

## 22. L4 完成定义

当一个新用户可以输入真实 context，系统自动维护有效画像，发现相关公开 SourceTarget，通过经过验证的 connector 追踪更新，并在当前新闻看板中看到结合确定性证据与有界 Agent 判断的优先队列时，L4 达到功能完成。

同时必须满足：

- 没有 hard-coded example 用户或来源被静默当成 runtime truth；
- 每个 Agent stage 都 typed、bounded、traced、replayable、independently disableable；
- 每个发布的 Agent 判断都落在 canonical evidence 上；
- connector 和 Agent failure 安全降级；
- 开发者能通过版本化 policy、prompt、schema 和 eval 改变行为；
- workflow 保持固定，不声称已经达到 L5 autonomous controller。
