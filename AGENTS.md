For future agents working in this repository:

- Read `docs/index.md` first for the documentation map.
- Treat files under `config/` as stable configuration for the current MVP unless the user explicitly asks to change them.
- Treat files under `src/` as the implemented demo source code. The current implemented fetch path is RSS-only; do not assume MCP/API/HTML sources are fetchable just because templates or contracts mention them.
- Put Codex-generated workspace artifacts under `codex-workspace/` instead of project docs or source directories. For example, planning/spec artifacts that previously lived under `docs/superpowers/` belong under `codex-workspace/docs/superpowers/`.
