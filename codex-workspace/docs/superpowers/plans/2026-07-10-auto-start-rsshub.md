# Auto-Start RSSHub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make normal workbench startup attempt to start Docker RSSHub by default while preserving an explicit opt-out.

**Architecture:** Reuse the existing `ensure_rsshub` helper and FastAPI lifespan hook. Only change the default `auto_start_rsshub` decision in `create_app`; do not add a scheduler or new Docker abstraction.

**Tech Stack:** FastAPI lifespan, pytest, monkeypatch.

---

### Task 1: Startup Default

**Files:**
- Modify: `tests/test_unified_web_app.py`
- Modify: `src/agentic-core/web_workbench/app.py`
- Modify: `README.md`
- Modify: `docs/current-demo-architecture.md`
- Modify: `docs/web-app/architecture.md`
- Modify: `docs/web-app/test-plan.md`

- [ ] **Step 1: Write failing tests**

Add tests proving default startup calls `ensure_rsshub`, and `FI_AUTO_START_RSSHUB=0` disables it.

- [ ] **Step 2: Verify red**

Run:

```bash
uv run --extra dev pytest tests/test_unified_web_app.py::test_workbench_auto_starts_rsshub_by_default tests/test_unified_web_app.py::test_workbench_can_disable_rsshub_auto_start_with_env -q
```

Expected: the default-start test fails because current code only starts RSSHub when `FI_AUTO_START_RSSHUB=1`.

- [ ] **Step 3: Implement minimal code**

Change `create_app` so `auto_start_rsshub` defaults to true unless `FI_AUTO_START_RSSHUB` is explicitly one of `0`, `false`, `no`, or `off`.

- [ ] **Step 4: Update docs**

Remove `FI_AUTO_START_RSSHUB=1` from normal startup commands and document `FI_AUTO_START_RSSHUB=0` as the opt-out.

- [ ] **Step 5: Verify**

Run:

```bash
uv run --extra dev pytest tests/test_unified_web_app.py -q
uv run --extra dev pytest -q
git diff --check
```
