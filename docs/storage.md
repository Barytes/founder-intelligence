# L4 Storage and Audit State

## SQLite source of truth

`data/app/founder-intelligence.db` 使用显式顺序 migration、foreign keys、WAL、transaction/savepoint 和 startup integrity check。

核心数据：

- append-only UserContextEvent/ProfileSnapshot；
- active profile pointer；
- SourceTarget/AcquisitionBinding histories；
- immutable ResolvedSourceSnapshot 与 active/pinned pointer；
- InboxItem；
- source discovery runs/candidate decisions/observations；
- AgentAssessment/RankedSignal score provenance；
- WorkflowRun/WorkflowStepTrace；
- persistent runtime kill switches。

Profile/source rollback 只移动 active pointer，不删除历史。Replay 从 persisted assessment/ranked signal/trace 重建 ordering，不调用 SearchProvider、connector 或模型。

## Agent audit 与搜索保留边界

三个 bounded Agent 节点使用同一个 `AgentNodeAudit` contract，只保存 model/prompt/policy version、usage、retry limit、replay 状态、trace event kind 与错误类型，不保存 chain-of-thought。Profile Compiler audit 随 immutable ProfileSnapshot 保存；Source Discovery audit 随 SourceDiscoveryRun 保存；News Assessment audit 随 WorkflowStepTrace 保存。

SearchProvider 的完整 normalized response 只作为本次 discovery 的内存输入。默认落库副本会清空 result title、description 与 rate-limit header，只保留 query、request ID、result URL、rank 和不可逆 result hash，以及另表中的 candidate decision/provenance。当前没有开启供应商 raw-result 长期存储；只有未来确认具体 plan 具备 storage rights 后，才可另行设计有 TTL 的 raw store。

## Artifact/handoff layer

- `data/canonical-items/latest.json`：latest canonical handoff；
- `data/store/items/YYYY-MM-DD.jsonl`：canonical append-only export；
- `data/store/runs/YYYY-MM-DD.jsonl`：store attempts；
- `data/signals/latest.json`：atomic latest-success dashboard artifact；
- `data/app/refresh-status.json`：operational status；
- `data/migrations/`：byte-identical YAML backup、latest report 与 append-only history；latest report 保留原始 rollback anchor。

JSONL 不再承担完整 L4 state database 的角色，但继续作为简单、可读、可导出的 canonical handoff。
