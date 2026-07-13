# 当前 L4 Web App 验证指南

## Automated gate

```bash
UV_CACHE_DIR=/private/tmp/founder-intelligence-uv-cache uv run --extra dev pytest -q
git diff --check
uv lock --check
```

覆盖必须包括：

- context -> ProfileStore，correction/unknown/provenance；
- SourceCatalog migration、snapshot、rollback；
- RSS/RSSHub/Inbox contracts 与 network policy；
- discovery cadence、outage、probation/lifecycle/reward-hack；
- baseline parity、evidence spans、hybrid policy、item/full fallback；
- exact L4 step order、lock、partial failure、safe publish；
- Web/Agent shared runner；
- Inspector detail、0-external-call replay、kill switch 和 rollback；
- missing/cross/same-origin matrix；
- legacy fallback and current dashboard compatibility。

## HTTP smoke

```bash
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

检查 `/`、`/agent`、`/settings`、`/inspector`、`/api/health`、`/api/profile/current`、`/api/sources`、`/api/refresh/status` 和 `/api/inspector/runs` 均返回 200；配置摘要不得包含 secret。

## Browser smoke

在隔离临时 root 上验证：

1. 三栏 dashboard 与原新闻卡结构仍工作；
2. 输入当前信息后 profile status 更新；
3. 分享普通/视频 URL 后显示 probation 或 unresolved 的诚实状态；
4. source tracking state 与 follow/unfollow 真正进入 API；
5. refresh 显示 step/degraded state；
6. signal detail 展示 baseline/Agent/final provenance；
7. Inspector 显示 timeline、profile/source/score evidence；
8. replay 显示 `external_calls=0`；
9. kill switch/rollback 操作受 same-origin 保护；
10. legacy YAML 明确标为 compatibility，不再冒充 source of truth。

写操作不得在主 repo 上使用测试数据。真实 provider/RSSHub smoke 可选，未配置 credential 时必须明确 degraded，不能伪造成功。
