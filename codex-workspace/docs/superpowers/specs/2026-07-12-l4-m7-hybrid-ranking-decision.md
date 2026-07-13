# L4 M7 AgentAssessment 与 Hybrid Ranking 决策记录

日期：2026-07-12

状态：完成。

## 执行形态选择

首版采用 bounded candidate pool + per-item assessment，不采用单个超大 batch：

- 单项失败可以精确 fallback，不会使整个队列失效；
- item ID、evidence span 和错误可以逐项审计；
- 长正文截断边界清晰；
- candidate pool 限制请求总量，避免对全部 canonical items 无界调用模型；
- 后续只有 recorded eval 证明 batch 在成本/延迟上显著更优且不降低稳定性时，才替换 Agent adapter 内部实现。

## 已实现

- 现有 scorer 原样抽为 `compute_baseline_assessment`，`build_signal` 兼容入口仍返回相同字段；
- candidate pool 组合 baseline Top-N、source diversity、new topic/entity、pinned source、shared-source update 和 deterministic bounded exploration；
- URL/content identity 去重，避免重复内容占据多个优先队列位置；
- typed News Assessment output：relevance、novelty、credibility、urgency、counter-signal、reasoning summary 和 exact evidence spans；
- Agent input 只包含必要 profile 字段；source name、provider、priority、private profile fields 和 credential 均不进入模型；
- title/summary/content 作为 untrusted data；Agent 无工具权限，schema 不存在 final score 或权重字段；
- verifier 检查 item ID、span boundary、quote equality、正文证据和 unsupported certainty claims；
- versioned `HybridRankingPolicy` 在代码中合成 baseline/Agent/final score；
- item-level failure、full failure 和 suspicious all-high distribution 均回退 deterministic score；
- dashboard 既有 `importance_score`、`relevance_score`、`total_score`、display fields 保持兼容，并新增 score provenance、assessment、candidate reason 和版本关联；
- assessment 与 ranked score provenance append-only 持久化，支持后续 Inspector/replay。

## Recorded golden eval

固定两项 golden fixture 中，deterministic baseline 把高优先级但低证据的宣传项排在 Top-1，相关但低优先级的事实项位于 Top-N 外侧。bounded exploration 召回后，合法 recorded assessment 使相关事实项成为 hybrid Top-1：

```text
baseline Top-1 precision: 0/1
hybrid Top-1 precision:   1/1
exploration recall:       1/1
recorded replay ordering: stable
valid assessment evidence coverage: 100% in golden fixture
```

这证明的是机制与 policy 在批准 fixture 上改善 ranking，不代表某个线上模型已经完成大规模用户盲评。真实模型/多 prompt regression 在 M9 继续运行；schema 通过或文案更流畅不能替代排序改善证据。

## Reward-hack 与 fallback

- 三项以上全部维度接近满分且无 counter-signal 时，batch calibration 失败并全部 fallback。
- credibility 不可仅凭来源名或文风判断，因为这些字段根本不进入 Agent input。
- prompt injection 只作为被评估文本，不增加工具、权限或 final-score 控制面。
- invalid/hallucinated/title-only span、空内容、长内容、duplicate 和 timeout 均有显式测试。
- 模型异常只保存异常类型，不持久化可能含敏感信息的 raw exception。

## 证据

```text
M7 focused: 33 passed
full suite: 219 passed
git diff --check: passed
```

R-01 至 R-14 均有 deterministic、recorded 或 contract 自动测试证据。
