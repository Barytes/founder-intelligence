# L4 M4 SourceCatalog 迁移记录

日期：2026-07-12

状态：完成。

## 已实现

- 只读 YAML semantic importer、dry-run、import history；
- YAML source -> SourceTarget + AcquisitionBinding；
- `source_templates` -> append-only inactive capability records；
- stable identity、duplicate URL convergence、explicit re-import；
- immutable `ResolvedSourceSnapshot`；
- fetch/ingestion 接受 snapshot/config object；
- source flag 开启时 runner 不再读取固定 YAML；
- Dashboard source list/toggle/import 通过 catalog facade；
- toggle 和 refresh 不写回 YAML，不做静默双向同步。

## Pressure test

- YAML 格式变化不产生新 import。
- invalid source 在 transaction 前完成验证，不污染 catalog。
- changed binding 通过显式 import 替换，旧 binding 进入 inactive history。
- duplicate URL 收敛为一个 target；legacy source bindings 仍可追踪。
- source order 显式持久化，避免 snapshot 改变 fetch 顺序。
- credential 仅保存 opaque env ref，不保存 secret value。

## 证据

```text
M4 focused: 78 passed in 2.59s
full suite: 176 passed in 3.08s
git diff --check: passed
config/sources.yml SHA-256 unchanged
```

S-01 至 S-10 中属于 SourceCatalog 的条款均为 `proven`；Connector 条款进入 M5。
