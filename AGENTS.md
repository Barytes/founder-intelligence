For future agents working in this repository:

- Read `docs/index.md` first for the documentation map.
- Treat files under `config/` as stable configuration unless the user explicitly asks to change them. In L4, `config/sources.yml` is a backed-up bootstrap/import artifact and `config/user-profile.yml` is legacy compatibility; SQLite SourceCatalog/ProfileStore are the default runtime truth.
- Treat files under `src/` as implemented source code. Current network acquisition connectors are RSS/RSSHub, plus user-supplied Inbox ingestion; do not assume MCP/API/HTML/browser sources are fetchable merely because contracts mention them.
- Put Codex-generated workspace artifacts under `codex-workspace/` instead of project docs or source directories. For example, planning/spec artifacts that previously lived under `docs/superpowers/` belong under `codex-workspace/docs/superpowers/`.

### 多分支并行开发
- 长期并行开发多个 feature 时，每个 feature 分支必须使用独立 git worktree；不要在同一工作目录中反复切换分支。各分支应尽量只修改自己的功能边界，公共接口、数据合同、运行状态目录或共享核心逻辑需要先形成明确文档/基础分支后再分别接入。

### 新功能开发流程
- 细化需求，直至用户没有异议
- 针对需求，设计功能实现方案，直至用户没有异议
- 设计功能测评方案，直至用户没有异议
- 具体需求、功能实现方案、测评方案需要使用文档记录
- 严格按照功能实现方案实现，直到通过测评方案内所有的测评
- Pressure test当前实现的功能，检查是否有测评方案未覆盖、reward-hack测评、需求理解偏差、需求不清、功能实现错误、实现方案没有可维护性和可持续性等漏洞。若有，列举漏洞，提供改进方案，用户确认后实施改进。改进后重新pressure test，进行循环迭代直至没有漏洞。
