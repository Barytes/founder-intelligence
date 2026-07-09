# Agentic Core 架构、实现方式与风险

本文描述当前 Agentic Core 的真实实现。它是一个本机开发用的 Python 组件，不是生产级托管服务。

## 位置与边界

代码位于：

```text
src/agentic-core/
  agentic_core/       Python Agentic Core 包
  web_workbench/      本机 FastAPI 工作台
```

`agentic_core` 是可嵌入组件，负责配置加载、LLM provider 适配、工具注册、对话循环和工具调用。`web_workbench` 是本机开发入口，负责聊天、独立设置页、provider 配置、API key 写入和调试展示。

当前 Agentic Core 绑定当前项目的本地文件和本地工具。Agent tool path 的 refresh 由 Python-native deterministic pipeline 完成；当前实现仍是 RSS-only，不会启用 MCP/API/HTML source template。

## 核心模块

```text
agentic_core/
  __init__.py
  config.py
  core.py
  messages.py
  run.py
  schemas.py
  providers/
    base.py
    openai_compatible.py
  tools/
    registry.py
    founder_tools.py
    pipeline_tools.py
    runtime_tools.py
  pipeline/
    fetch_rss.py
    ingest_adapter_output.py
    store_canonical_jsonl.py
    build_signals.py
    runner.py
```

- `schemas.py` 定义配置、provider、tool、run result 等 Pydantic model。
- `config.py` 读取 `config/agentic-core.example.yml`、可选本机 `config/agentic-core.local.yml` 和 `.env`，并根据 active provider profile 派生实际运行 provider。
- `providers/openai_compatible.py` 通过 OpenAI-compatible Chat Completions API 调用模型。
- `tools/registry.py` 注册工具、导出 provider tool schema，并在执行 handler 前做本地参数校验。
- `tools/founder_tools.py` 提供本地 artifact 工具：读取 signals、读取 canonical items、写 agentic artifact。
- `tools/runtime_tools.py` 提供只读运行状态工具：读取 refresh status 和最新 store run。
- `tools/pipeline_tools.py` 提供受控 workflow 工具：调用 Python-native pipeline runner 触发 RSS-only refresh。
- `pipeline/` 提供 Python-native deterministic pipeline，用于 Agent tool path 的 RSS fetch、ingestion、store、signal build 和 runner orchestration。
- `core.py` 实现 Agentic Core 对话循环。
- `run.py` 提供 CLI smoke 入口。

## 配置模型

配置分三层加载：

1. `config/agentic-core.example.yml`：提交到仓库的默认模板。
2. `config/agentic-core.local.yml`：本机覆盖配置，已 gitignore。
3. `.env`：API key 等本机 secret，已 gitignore。

`provider_profiles` 同时承载 provider templates 和已保存配置。工作台 UI 会把它们拆成两个概念：

- `Provider Type`：OpenAI、DeepSeek、OpenRouter、Custom 等模板。
- `Saved Configuration`：用户保存过的可直接使用的配置，只来自 gitignored `config/agentic-core.local.yml` 中实际存在的 profile。

默认模板不会显示为 saved configuration。没有保存过任何配置时，`Saved Configuration` 只显示 `New Configuration`；OpenAI、DeepSeek、OpenRouter、Custom 仍只在 `Provider Type` 中作为模板出现。

保存新配置时，`Config Name` 会生成 profile id 和 env var。例如：

```text
Config Name: Work DeepSeek
profile id: work_deepseek
API key env: WORK_DEEPSEEK_LLM_API_KEY
```

API key 写入 `.env`，model/base URL/active config 写入 `config/agentic-core.local.yml`。

## 运行流

一次对话运行大致如下：

```text
Workbench or Python caller
        |
        v
AgenticCore.from_config(...)
        |
        v
load_agentic_config(...)
        |
        v
build_provider(config.provider)
        |
        v
ToolRegistry.provider_tools()
        |
        v
LLM complete(messages, tools)
        |
        +-- no tool calls --> final RunResult
        |
        +-- tool calls ----> ToolRegistry.run(...)
                              |
                              v
                         append tool messages
                              |
                              v
                         next LLM turn
```

循环最多运行 `agent.max_turns` 次。provider 返回普通 assistant message 时结束；provider 返回 tool calls 时执行工具并把工具结果作为 tool message 放回上下文。

## 工具边界

当前默认工具是本地、显式、窄权限工具：

- `read_signals`：读取 repo 内 JSON，默认 `data/signals/latest.json`。
- `read_canonical_items`：读取 repo 内 JSON，默认 `data/canonical-items/latest.json`。
- `read_refresh_status`：读取固定路径 `data/app/refresh-status.json`，缺失时返回 `idle`。
- `read_latest_run`：读取 `data/store/runs/*.jsonl` 中最新一条 run record。
- `run_refresh_pipeline`：通过 Python-native `agentic_core.pipeline.runner.PipelineRunner` 触发一次 RSS-only refresh。
- `write_agentic_artifact`：只允许写到 `data/agentic/` 下。

`read_signals` 和 `read_canonical_items` 的 provider-facing schema 不暴露 path 参数；测试和本机 caller 可通过 context 覆盖 fixture path。`ToolRegistry.run` 会在本地执行前拒绝 schema 外参数，因此 provider schema 不是唯一边界。

`run_refresh_pipeline` 不接受 command、argv、script、path、source id 或 config path。它调用 Python-native runner，由 runner 负责 lock、status、产物校验、失败保护和发布语义。

这些工具不会执行任意 shell，不会修改 `config/`。`run_refresh_pipeline` 会按当前 RSS-only pipeline 抓取外部 RSSHub 信息源，但不会启用 MCP/API/HTML source template。

## Web 工作台

`web_workbench/app.py` 是当前统一 FastAPI HTTP 后端。它同时服务信号控制台和 Agentic Core 工作台，默认本机运行：

```bash
PYTHONPATH=src/agentic-core uv run python -m uvicorn web_workbench.app:app --host 127.0.0.1 --port 4567
```

工作台页面：

- `GET /`：信号控制台。
- `GET /agent`：Agentic Core 工作台。
- `GET /settings`：本机配置页，管理 Agent provider 配置和 RSSHub/GitHub 相关 `.env` secret。

Agent 主要 API：

- `GET /api/agent/default-config`：返回安全配置摘要，不返回 API key。
- `POST /api/agent/provider-settings`：保存 provider 配置，secret 写 `.env`，非 secret 写 local YAML。
- `POST /api/agent/chat`：调用 `AgenticCore` 运行一次聊天。
- `GET /api/settings/env`：返回 `.env` 中 GitHub token 的脱敏状态。
- `PUT /api/settings/env`：保存 `GITHUB_ACCESS_TOKEN` 到 `.env`，不在响应中回传明文。

旧的 `/api/default-config`、`/api/provider-settings` 和 `/api/chat` 仍作为迁移期兼容 alias 保留。Agent 静态 UI 位于 `src/agentic-core/web_workbench/static/`。

## 已知风险与漏洞

当前版本适合本机开发，不适合直接暴露到网络。

1. **无身份认证**
   工作台没有登录、token、CSRF 防护。如果绑定到非 localhost，任何能访问端口的人都可能改 `.env`、切换 provider 或调用模型。

2. **API key 明文落盘**
   `.env` 以明文存储 API key。仓库已 ignore，但本机文件权限、备份、终端历史和截图仍可能泄露。

3. **Base URL 可配置**
   用户可以把 base URL 指向任意 OpenAI-compatible endpoint。这是功能需求，但如果误配，API key 会发送到该 endpoint。

4. **Provider profile 名称规范化可能碰撞**
   `Work DeepSeek` 和 `Work-DeepSeek` 都会映射到 `WORK_DEEPSEEK_LLM_API_KEY`。当前会阻止与已有 profile id 冲突，但仍需要用户理解命名规则。

5. **Prompt injection**
   模型会读取本地 signals/canonical items。来自 RSS 的内容可能包含指令式文本，模型可能被影响。当前工具边界较窄，但最终文本仍可能受污染。

6. **工具路径边界依赖 schema 和 registry 校验**
   `read_signals` 和 `read_canonical_items` 的模型可见 schema 已不暴露 path，但本地 caller context 仍可覆盖测试路径。后续新增工具时必须继续保持 provider schema、本地参数校验和 handler allowlist 三层一致。

7. **缺少 provider 请求限流和预算控制**
   当前没有 token/cost budget、并发限制或速率限制。误操作可能造成较高 API 调用成本。

8. **错误信息可能泄露局部路径**
   结构化错误会返回异常文本，可能包含本机路径。当前是本机开发可接受，外部服务需要脱敏。

9. **Local YAML 写入没有并发锁**
   多个浏览器同时保存 provider 设置时，可能发生最后写入覆盖前一次写入。

10. **依赖 OpenAI-compatible schema**
    非完全兼容的厂商可能返回不同 tool call 字段，当前 adapter 不保证兼容所有厂商。

## 加固建议

- 保持工作台只绑定 `127.0.0.1`。
- 不把 `.env` 和 `config/agentic-core.local.yml` 提交到 git。
- 为 provider 保存接口增加本机 session token 或随机启动 token。
- 为 LLM 调用增加成本预算、超时、速率限制和请求日志。
- 对工具可读路径做 allowlist，而不是任意 repo 内 JSON。
- 对错误响应做路径和 secret 脱敏。
- 如果要用于多人或远程环境，迁移到带认证、审计和加密 secret storage 的部署方式。
