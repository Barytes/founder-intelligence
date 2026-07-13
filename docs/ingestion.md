# Canonical Ingestion

Ingestion 将 connector result 与 Inbox item 转换/合并为统一 canonical items。

## Inputs and output

- RSS/RSSHub adapter output；
- SQLite Inbox items（`origin=user_shared`）；
- `config/ingestion-rules.yml`；
- 输出 `data/canonical-items/latest.json`。

## Responsibilities

- HTML/text cleanup and whitespace normalization；
- datetime/link normalization and tracking-parameter removal；
- provider-aware dedupe key and content hash；
- within-run duplicate removal；
- quality flags；
- Inbox minimal fact preservation，即使持续来源解析失败；
- provenance 保留 target/binding/origin。

Canonical failure 是发布硬边界：workflow 不进入 baseline score、Agent assessment 或 publish。Canonical JSON 同时写入 append-only JSONL handoff，但 source/profile/workflow state 已由 SQLite 持久化。
