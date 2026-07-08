# 当前 Web App 验证指南

本文记录当前 Web app 的验证方式。它描述的是已经实现的运行路径，不是未来开发计划。

## 验证目标

当前验证应证明：

- Web app 首页由 `src/web/public/` 提供，不依赖旧静态 sample data。
- 页面数据来自 `/api/signals/latest`、`/api/refresh/status`、`/api/sources`。
- `user-profile.yml` 编辑器真实读写 `config/user-profile.yml`。
- source overlay 真实读写 `config/sources.yml`。
- 未实现的 MCP/API/HTML/file source 不会被当前 refresh 执行。
- refresh runner 按 RSS-only pipeline 顺序执行，并保留 latest-success 语义。
- 安全边界仍然拒绝跨 origin 写操作和命令参数。

## 自动化测试

从项目根目录运行：

```bash
ruby tests/test_web_app.rb
ruby tests/test_web_core.rb
node --check src/web/public/app.js
ruby -c src/web_app.rb
ruby -c src/web/app.rb
ruby -c src/web/data_repository.rb
ruby -c src/web/pipeline_runner.rb
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
- `PipelineRunner` 的成功发布、失败不覆盖、lock、store summary、signal diff。

## HTTP Smoke

启动本地 server：

```bash
ruby src/web_app.rb --port 4567
```

检查首页：

```bash
curl -s -o /tmp/fi-main-check.html -w "%{http_code} %{content_type}\n" http://127.0.0.1:4567/
```

期望：

```text
200 text/html; charset=utf-8
```

## 真实浏览器 Smoke

使用 Codex `@浏览器` in-app browser 验证当前页面。为了避免污染真实 `config/`，写入类测试应使用临时 root：

```bash
rm -rf /private/tmp/fi-browser-root
mkdir -p /private/tmp/fi-browser-root/config /private/tmp/fi-browser-root/data/signals
cp config/user-profile.yml /private/tmp/fi-browser-root/config/user-profile.yml
cp config/sources.yml /private/tmp/fi-browser-root/config/sources.yml
cp data/signals/latest.json /private/tmp/fi-browser-root/data/signals/latest.json
ruby src/web_app.rb --port 4568 --root /private/tmp/fi-browser-root
```

浏览器 smoke 应覆盖：

- 打开 `http://127.0.0.1:4568/`，确认 command bar、profile 入口、source folders 渲染。
- 打开 `user-profile.yml` modal，编辑合法 profile，保存后状态显示 `已保存 config/user-profile.yml；下次刷新生效`。
- 打开 source folder overlay，启用或停用真实 RSS source，确认按钮和 meta 状态改变。
- 打开 `sources.yml` 编辑器，确认原文包含 `version: 1` 和真实 source id，保存后状态显示 `已保存 config/sources.yml；下次刷新生效`。
- 文件层确认临时 root 被写入，而不是主 repo 配置被测试污染。

本轮真实浏览器测试曾发现 WEBrick 不支持浏览器发起的 `PATCH` 请求，导致 source toggle 返回非 JSON 错误。当前浏览器运行路径已改为 `POST /api/sources/:id`，App 内部仍保留 `PATCH` 兼容。

## 不应回归的旧行为

以下行为不应重新出现：

- 页面显示旧 profile 草稿入口，而不是 `user-profile.yml`。
- profile/source 状态只保存在浏览器端状态里。
- 前端维护独立 hardcoded source catalog。
- source 删除按钮或只影响 UI 的启停按钮。
- Web app 运行时依赖 `assets/sample-data.js`。
- 首页直接 serve 或 iframe `data/dashboard/index.html`。
- 页面把 MCP/API/HTML/file source 展示成当前可运行 fetcher。
