# Auto-Start RSSHub Design

## Requirement

Starting the local FastAPI workbench should also attempt to start the Docker RSSHub service by default.

## Behavior

- Default workbench startup calls `docker compose -f config/docker-compose.yml up -d rsshub`.
- `FI_AUTO_START_RSSHUB=0` disables the startup attempt.
- `FI_AUTO_START_RSSHUB=1` remains accepted and behaves the same as the default.
- Docker startup failure does not block the workbench. The startup result is recorded in app state, and refresh can report pipeline failure normally.

## Files

- `src/agentic-core/web_workbench/app.py`: change `create_app` default auto-start logic.
- `tests/test_unified_web_app.py`: cover default startup and explicit disable.
- `README.md`, `docs/current-demo-architecture.md`, `docs/web-app/architecture.md`, `docs/web-app/test-plan.md`: update startup command text.

## Evaluation

- Focused tests:
  `uv run --extra dev pytest tests/test_unified_web_app.py -q`
- Full suite:
  `uv run --extra dev pytest -q`
- Diff hygiene:
  `git diff --check`
