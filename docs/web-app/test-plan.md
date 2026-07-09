# 当前 Web App 验证指南

本文记录当前 Web app 的验证方式。它描述的是已经实现的运行路径，不是未来开发计划。

## 验证目标

当前验证应证明：

- Web app 首页由 `src/web/public/` 提供，不依赖旧静态 sample data。
- Agent Workbench 由同一个 FastAPI app 在 `/agent` 提供。
- Settings 页面由同一个 FastAPI app 在 `/settings` 提供。
- 页面数据来自 `/api/signals/latest`、`/api/refresh/status`、`/api/sources`。
- `user-profile.yml` 编辑器真实读写 `config/user-profile.yml`。
- source overlay 真实读写 `config/sources.yml`。
- Settings 页面可写 provider settings 到 `.env`/`config/agentic-core.local.yml`，并可写 `GITHUB_ACCESS_TOKEN` 到 `.env`。
- 未实现的 MCP/API/HTML/file source 不会被当前 refresh 执行。
- Python refresh runner 调用 Ruby RSS-only pipeline scripts，并保留 latest-success 语义。
- 安全边界仍然拒绝跨 origin 写操作和命令参数。

## 自动化测试

从项目根目录运行：

```bash
uv run --extra dev pytest
ruby -c src/fetch_rss.rb
ruby -c src/ingest_adapter_output.rb
ruby -c src/store_canonical_jsonl.rb
ruby -c src/build_signals.rb
```

当前测试覆盖：

- 首页 shell、静态资源和 brand logo。
- 前端不使用 `window.FI_*` sample globals。
- `/api/signals/latest` latest-success 读取语义。
- `/api/profile` 读取、保存和 YAML/profile 语义校验。
- `/api/sources` 读取、保存和 RSS-only source 语义校验。
- `POST /api/sources/:id` 启用/停用真实 RSS source。
- `PATCH /api/sources/:id` 作为 App 内兼容路径保留。
- `/api/refresh` 的 same-origin、命令参数拒绝和同步返回语义。
- Python `PipelineRunner` 的成功发布、失败不覆盖、lock、store summary、signal diff。
- Agent Workbench provider 和 chat API 在 `/api/agent/*` 下可用，旧 `/api/*` agent aliases 暂时保留。
- `/settings`、`/api/settings/env`、GitHub token 脱敏状态和写入 `.env`。
- Provider settings 和 GitHub token 写入拒绝 cross-origin 请求，且不泄露 secret。
- `Saved Configuration` 只包含 local config 中用户保存过的 profile，不包含 OpenAI/DeepSeek/OpenRouter 默认模板。

## HTTP Smoke

启动本地 server：

```bash
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

检查首页：

```bash
curl -s -o /tmp/fi-main-check.html -w "%{http_code} %{content_type}\n" http://127.0.0.1:4567/
curl -s -o /tmp/fi-agent-check.html -w "%{http_code} %{content_type}\n" http://127.0.0.1:4567/agent
curl -s -o /tmp/fi-settings-check.html -w "%{http_code} %{content_type}\n" http://127.0.0.1:4567/settings
curl -s -w "\n%{http_code}\n" http://127.0.0.1:4567/api/health
curl -s -w "\n%{http_code}\n" http://127.0.0.1:4567/api/agent/default-config
curl -s -w "\n%{http_code}\n" http://127.0.0.1:4567/api/settings/env
```

期望：

```text
200 text/html; charset=utf-8
200 text/html; charset=utf-8
200 text/html; charset=utf-8
{"status":"ok"} or pretty JSON equivalent with 200
Agent config JSON with 200 and no API key secret. Default provider templates appear under `provider_templates`; `saved_configs.items` is empty until local profiles are saved.
Settings env JSON with 200 and no GitHub token secret
```

## 真实浏览器 Smoke

使用 Codex `@浏览器` in-app browser 验证当前页面。为了避免污染真实 `config/`，写入类测试应使用临时 root：

```bash
rm -rf /private/tmp/fi-browser-root
mkdir -p /private/tmp/fi-browser-root/config /private/tmp/fi-browser-root/data/signals
cp config/user-profile.yml /private/tmp/fi-browser-root/config/user-profile.yml
cp config/sources.yml /private/tmp/fi-browser-root/config/sources.yml
cp config/agentic-core.example.yml /private/tmp/fi-browser-root/config/agentic-core.example.yml
cp data/signals/latest.json /private/tmp/fi-browser-root/data/signals/latest.json
touch /private/tmp/fi-browser-root/.env
FI_REPO_ROOT=/private/tmp/fi-browser-root FI_ALLOWED_ORIGINS=http://127.0.0.1:4568,http://localhost:4568 PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4568
```

浏览器 smoke 应覆盖：

- 打开 `http://127.0.0.1:4568/`，确认 command bar、profile 入口、source folders 渲染。
- 通过顶部导航进入 `/agent`，再从 Agent Workbench 返回 `/`。
- 通过顶部导航进入 `/settings`，确认 Provider Type 展示默认模板，Saved Configuration 初始只显示 New Configuration。
- 在 `/settings` 保存一个命名 provider 配置，确认它出现在 Saved Configuration，且默认模板不作为 saved config 出现。
- 在 `/settings` 保存 GitHub token，确认页面只显示脱敏状态，临时 root `.env` 被写入。
- 打开 `user-profile.yml` modal，编辑合法 profile，保存后状态显示 `已保存 config/user-profile.yml；下次刷新生效`。
- 打开 source folder overlay，启用或停用真实 RSS source，确认按钮和 meta 状态改变。
- 打开 `sources.yml` 编辑器，确认原文包含 `version: 1` 和真实 source id，保存后状态显示 `已保存 config/sources.yml；下次刷新生效`。
- 文件层确认临时 root 被写入，而不是主 repo 配置被测试污染。

历史真实浏览器测试曾发现旧 WEBrick 不支持浏览器发起的 `PATCH` 请求，导致 source toggle 返回非 JSON 错误。当前 FastAPI 后端支持 `POST` 和 `PATCH`，浏览器运行路径仍使用 `POST /api/sources/:id`。

## 不应回归的旧行为

以下行为不应重新出现：

- 页面显示旧 profile 草稿入口，而不是 `user-profile.yml`。
- profile/source 状态只保存在浏览器端状态里。
- 前端维护独立 hardcoded source catalog。
- source 删除按钮或只影响 UI 的启停按钮。
- Web app 运行时依赖 `assets/sample-data.js`。
- 首页直接 serve 或 iframe `data/dashboard/index.html`。
- 页面把 MCP/API/HTML/file source 展示成当前可运行 fetcher。
