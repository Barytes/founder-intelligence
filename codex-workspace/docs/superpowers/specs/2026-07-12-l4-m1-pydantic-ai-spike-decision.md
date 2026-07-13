# L4 M1 PydanticAI 单一 Runtime 切换记录

日期：2026-07-12

状态：完成。PydanticAI 已成为唯一 Agent runtime，自建 Agent loop 与 provider 实现已删除。

## 1. 修订后的 M1 完成定义

M1 只有同时满足以下条件才完成：

1. OpenAI-compatible provider 可由现有配置构造并保留 timeout；
2. typed dependency、typed output、function tool、有限重试可运行；
3. request、token、tool-call 三类预算由本地 runtime 强制执行；
4. model/tool events 可审计，OpenTelemetry 可导出到本地 collector；
5. TestModel/FunctionModel 测试不访问网络、不要求 API key；
6. 现有 `ToolRegistry` 的 enabled/argument/handler 权限边界不可绕过；
7. `AgenticCore.run()` 继续返回既有 `RunResult`，保留 tool message、usage、artifact、error 和默认 context 合同；
8. `AgenticCore` 默认且唯一构造 `PydanticAIRuntime`；
9. 删除自建 provider package、Agent turn loop、provider injection 和旧 provider tests；
10. Web/CLI 使用完成后关闭 runtime 自建 client；
11. framework import 只存在于 runtime adapter，不进入 domain、tool handler、pipeline 或 Web route；
12. 新环境可按 committed `uv.lock` 重建。

本次不使用 feature flag，不保留 legacy fallback。若需要回滚，通过版本控制恢复整个旧版本，而不是长期维护双实现。

## 2. 最终结构

```text
AgenticCore facade
  -> PydanticAIRuntime                 # 唯一默认 runtime
       -> PydanticAI Agent
       -> OpenAIProvider/OpenAIChatModel
       -> RegistryToolset
            -> ToolRegistry.run()      # 本地权限最终边界
       -> UsageLimits
       -> RuntimeTraceEvent / OTel
```

删除：

```text
src/agentic-core/agentic_core/providers/
tests/test_provider.py
AgenticCore 内的 provider.complete(...) turn loop
AgenticCore(provider=...) 注入入口
```

保留 `AgentRuntime` protocol 是为了测试和未来替代 adapter，而不是保留旧实现。

## 3. 依赖锁定

- `pydantic-ai-slim[openai]>=2.9.0,<3.0.0`；
- `opentelemetry-sdk>=1.43.0,<2.0.0`；
- `uv.lock` 纳入版本控制；
- 新 checkout 使用 `uv sync --frozen --extra dev`；
- `uv lock --check` 是门禁。

## 4. 兼容合同

切换后必须继续证明：

- model tool call 进入同一个 `ToolRegistry`；
- tool name、arguments、result、error 和 artifact path 可见；
- tool result 以兼容 `role=tool` message 返回；
- final text 和 normalized total usage 保留；
- `agent.max_turns` 映射为本地 request limit，超限仍返回 `max turns reached`；
- `AgenticCore` 在显式 context 之外继续注入 signals、canonical items 和 artifact 默认路径；
- Web/CLI 返回的仍是 `RunResult` JSON contract。

## 5. Trace 与安全

默认不连接 Logfire，不要求商业服务。runtime 使用 OpenTelemetry 标准接口，可接本机或 in-memory exporter。

`RuntimeTraceEvent` 记录有序的 user/model/tool/retry 事件、tool name、call id、参数或结果。它不保存 chain-of-thought；`thinking`/`reasoning` part 内容强制替换为 `[redacted]`。

## 6. Pressure test

| 风险 | 攻击方式 | 修正/证据 | 状态 |
| --- | --- | --- | --- |
| 假切换 | 默认仍走旧 loop | default-runtime test + constructor source guard | 已关闭 |
| 旧实现死代码残留 | provider package 仍可 import | 文件删除 + forbidden-symbol scan | 已关闭 |
| legacy provider 旁路 | 继续允许 `AgenticCore(provider=...)` | constructor signature test | 已关闭 |
| ToolRegistry 被绕过 | 模型提交额外参数 | adapter 最终调用 `registry.run()`；handler 未执行且错误被记录 | 已关闭 |
| 假 typed output | 只测试合法值 | invalid -> retry -> valid 与 retry exhaustion | 已关闭 |
| 预算只是提示 | 模型持续调用 | request/token/tool-call 三个 failure tests | 已关闭 |
| 测试误调真实 provider | 本机恰有 API key | `ALLOW_MODEL_REQUESTS=False` + FunctionModel/TestModel | 已关闭 |
| framework 泄漏 | Web/domain 直接 import PydanticAI | import scan guard | 已关闭 |
| trace 绑定商业服务 | Logfire 成为运行前提 | OTel in-memory exporter test | 已关闭 |
| trace 保存私密推理 | ThinkingPart 原文进入审计 | reasoning redaction test | 已关闭 |
| client 泄漏 | Web/CLI 每次构造 provider 不关闭 | `close()` ownership test + Web/CLI finally | 已关闭 |
| 删除旧测试导致覆盖下降 | 只保留 framework unit test | 重写 core golden-contract tests + full suite | 已关闭 |
| 框架升级漂移 | 新 checkout 解析不同 API | 主版本上界 + lock + frozen sync | 已关闭 |

## 7. 可执行验收

```bash
env UV_CACHE_DIR=/private/tmp/uv-cache uv lock --check

env UV_CACHE_DIR=/private/tmp/uv-cache uv run --frozen --extra dev pytest \
  tests/test_pydantic_ai_cutover.py \
  tests/test_pydantic_ai_runtime.py \
  tests/test_core_loop.py \
  tests/test_tools.py \
  tests/test_pipeline_tools.py \
  tests/test_runtime_tools.py \
  tests/test_cli.py \
  tests/test_workbench_api.py -q

env UV_CACHE_DIR=/private/tmp/uv-cache uv run --frozen --extra dev pytest -q
git diff --check
```

源码残留检查：

```bash
test ! -e src/agentic-core/agentic_core/providers
test ! -e tests/test_provider.py
rg "ProviderResponse|ProviderToolCall|OpenAICompatibleProvider|build_provider|for _turn in range" \
  src/agentic-core/agentic_core
```

最后一条 `rg` 必须无匹配。

## 8. 决策

**PydanticAI 2.x 现在是 Agentic Core 的唯一 runtime。**

PydanticAI 只负责模型、typed output、工具调用、retry、budget 和 trace；它不接管 `PipelineRunner`、canonical contract、connector、repository、确定性验证或评分 policy。未来若更换框架，通过 `AgentRuntime` adapter 完整替换，而不是重新引入仓库自建 turn loop。

## 9. 最终证据

```text
clean-env cutover focused: 76 passed in 3.19s
full suite: 119 passed in 2.88s
uv lock --check: resolved 46 packages, passed
git diff --check: passed
legacy providers directory: absent
legacy provider test: absent
legacy source symbols: no matches
config/sources.yml SHA-256: a07eeb5ec281abf96c53bad7b3d5e5ffa927af6ea46f4e797ce01523bb157a44
```

M1-01 至 M1-22 全部为 `proven`。本次切换没有启用其他 L4 feature flag，没有修改当前 RSS pipeline、Dashboard 或 sources runtime contract。
