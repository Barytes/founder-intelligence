# Signal Processing：Deterministic Baseline + Agent Judgment

当前评分不是 LLM-only，也不是旧版纯规则。

## Pipeline

1. `compute_baseline_assessment` 保留既有 importance/relevance/display contract。
2. Candidate pool 从 baseline Top-N、source diversity、new topic/entity、pinned/shared source 和 deterministic exploration 取有界集合。
3. News Assessment Agent 输出 relevance、novelty、credibility、urgency、counter-signal、reasoning summary 和 exact evidence spans。
4. 本地 verifier 检查 item ID、span boundary/quote、正文支持、数值范围和 prohibited claims。
5. `HybridRankingPolicy` 在代码中计算 Agent component 与 final score；模型不能返回权重或 final score。
6. invalid/timeout 逐项 fallback；全部失败发布合法 deterministic-only artifact。

每个 signal 保留旧 dashboard 字段，并可新增：

- `score_provenance.baseline_components`；
- baseline/Agent/final score；
- policy/assessment/workflow/profile/source snapshot IDs；
- candidate reasons；
- Agent valid/fallback state。

重复 item 不会占多个排名位置。三项以上异常全高分分布会被 calibration policy 拒绝。Recorded golden fixture 证明机制能把相关事实项从 deterministic Top-N 外召回并改善 Top-1；这不替代真实用户盲评。
