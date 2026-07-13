# L4 M2 Domain、SQLite 与 Repository 实现记录

日期：2026-07-12

状态：完成。

## 实现

- `agentic_core/l4/domain.py`：versioned、`extra=forbid`、frozen domain contracts 和明确 enums。
- `agentic_core/l4/hashing.py`：canonical hash、URL normalization、稳定 SourceTarget identity 和 idempotency key。
- `agentic_core/l4/database.py`：stdlib SQLite、foreign keys、WAL、顺序 migration、nested transaction、integrity check。
- `agentic_core/l4/repositories.py`：context、profile、source、assessment、workflow repositories。

动态数据库默认路径为 `data/app/founder-intelligence.db`，已被现有 `data/app/` ignore 规则覆盖。测试使用 `:memory:`。

## 不变量

- ContextEvent、ProfileSnapshot、source/binding history、source snapshot、assessment、ranked signal 和 step trace 由 trigger 强制 append-only。
- ProfileSnapshot 写入与 active pointer 切换在同一 transaction。
- SourceTarget identity 优先 `(source_kind, provider, canonical_external_id)`；无 external ID 时才使用 `v1` URL identity。
- URL 是可变属性，不作为有 external ID target 的主键。
- 数据库损坏时明确失败，原文件不删除、不重建。
- migration 单步 transaction；失败步骤的 schema 和 version 一并回滚。
- repository/domain 不 import FastAPI 或 PydanticAI。

## Pressure test

| 风险 | 反制 | 状态 |
| --- | --- | --- |
| 文件存在即算数据库完成 | 真实 transaction/repository behavior tests | 已关闭 |
| idempotency key 重用覆盖事实 | 同内容返回既有 event，不同内容冲突 | 已关闭 |
| snapshot 插入后 active 切换失败 | injected failure rollback test | 已关闭 |
| SQLite 损坏静默重建 | byte-preservation corruption test | 已关闭 |
| migration DDL 留半状态 | failing migration schema/version rollback | 已关闭 |
| URL 变化制造重复 target | external identity invariance test | 已关闭 |
| 状态覆盖后无历史 | target/binding append-only history | 已关闭 |
| neutral profile 偷带硬编码兴趣 | EffectiveProfile invariant | 已关闭 |
| framework lock-in 泄漏 | source import scan | 已关闭 |

## 最终证据

```text
M2 focused: 27 passed in 0.86s
full suite: 146 passed in 3.23s
git diff --check: passed
config/sources.yml SHA-256 unchanged:
a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44
```

M2 没有改变当前 pipeline 输入、Dashboard 或 feature flag 默认值。
