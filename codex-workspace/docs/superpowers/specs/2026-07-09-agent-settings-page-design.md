# Agent Settings Page Design

## Requirement

Move Agent Workbench provider configuration out of the chat workbench and into a dedicated settings page. The settings page must be reachable from the shared navigation, preserve the current local-console visual style, and support saving a GitHub token into the project root `.env`.

## Design

- Add `GET /settings` served by `src/agentic-core/web_workbench/static/settings.html`.
- Keep `/agent` focused on chat, provider status, tool list, and tool-call log.
- Move provider configuration controls to `settings.html` with a dedicated `settings.js`.
- Add `GET /api/settings/env` to report `GITHUB_ACCESS_TOKEN` status without returning the token.
- Add `PUT /api/settings/env` to save `GITHUB_ACCESS_TOKEN` to `.env`.
- Reuse the existing `.env` update helper so comments and unrelated environment lines are preserved.
- Reject cross-origin `.env` writes through the existing same-origin guard.
- Show only a masked token preview in API responses and UI.

## Testing

- API tests cover `/settings`, safe GitHub token status, GitHub token save, cross-origin rejection, and Workbench config extraction.
- Existing provider-setting tests continue to cover provider API key writes and secret redaction.
- Full repository tests should pass with the existing FastAPI/TestClient suite.

## Pressure Test

- Secret leakage: responses never include the raw GitHub token.
- Config drift: provider settings still write through the existing local YAML and `.env` path.
- Scope creep: this does not add source editing or RSSHub route configuration to the settings page.
- Runtime boundary: writing `.env` does not restart Docker/RSSHub automatically; the current process env is updated for app-level reads.
