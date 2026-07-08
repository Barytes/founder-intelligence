# Agentic Core Design

Date: 2026-07-08

## Status

Approved design direction. Ready for user review before implementation planning.

## Goal

Add a callable, configurable Agentic Core component to the Founder Intelligence MVP.

The component must:

- support multi-turn conversation with a large language model
- support model-requested tool calls
- allow LLM provider, model, base URL, and API token wiring to be configured
- embed into this project as a reusable component, not only as a standalone app
- provide a local-only web workbench for development conversation and configuration
- use `.env` for API tokens and keep tokens out of committed YAML config

## Non-Goals

This first version will not:

- change the existing deterministic RSS fetch, ingestion, storage, or signal pipeline
- modify existing stable MVP config files unless explicitly requested later
- implement MCP, API, or HTML fetchers
- add a scheduler
- add user accounts, login, multi-user isolation, or deployment security
- execute external side effects beyond registered local project tools
- store or display API tokens in the browser UI

## Current Project Boundary

The current implemented demo is a local deterministic Ruby pipeline:

```text
RSS fetch
-> canonical ingestion
-> JSONL storage
-> rule-based signal scoring
-> dashboard artifacts
```

The implemented fetch path is RSS-only. Files under `config/` are stable MVP configuration, and files under `src/` are the implemented demo source code.

Agentic Core should therefore be added beside the current pipeline. It should consume existing artifacts such as `data/signals/latest.json` and `data/canonical-items/latest.json`, then write its own agentic artifacts under a separate output path such as `data/agentic/`.

## Recommended Approach

Build a thin Python Agentic Core with explicit provider and tool abstractions, plus a local FastAPI workbench that uses the same core.

This is preferred over adopting a full agent framework in the first version because the project needs a small embeddable component with clear boundaries, not a framework-owned runtime. The design should still leave room to add framework adapters later if the project grows into long-running orchestration, multi-agent workflows, or richer tracing.

## Architecture

```text
Founder Intelligence artifacts
        |
        v
AgenticCore.run(messages, context, options)
        |
        +-- ProviderAdapter
        |     +-- OpenAICompatibleProvider
        |     +-- future: AnthropicProvider
        |     +-- future: GeminiProvider
        |
        +-- ToolRegistry
        |     +-- read_signals
        |     +-- read_canonical_items
        |     +-- write_agentic_artifact
        |     +-- future: search / fetch / MCP tools
        |
        +-- Conversation state
        +-- Tool execution log
        +-- Structured run result
        |
        v
data/agentic/latest.json
data/agentic/latest.md
```

## Proposed File Layout

```text
agentic_core/
  __init__.py
  core.py
  config.py
  messages.py
  schemas.py
  providers/
    __init__.py
    base.py
    openai_compatible.py
  tools/
    __init__.py
    registry.py
    founder_tools.py

web_workbench/
  app.py
  static/
    index.html
    app.js
    styles.css

config/
  agentic-core.example.yml
  agentic-core.local.yml   # gitignored local overrides

.env.example
```

The example YAML stays committed as the project template. Machine-specific non-secret preferences are written to gitignored `config/agentic-core.local.yml`. API tokens stay out of YAML and are loaded from `.env`.

## Core API

The core should be callable from Python:

```python
from agentic_core import AgenticCore

core = AgenticCore.from_config("config/agentic-core.example.yml")
result = core.run(
    messages=[
        {"role": "user", "content": "Analyze today's founder intelligence signals."}
    ],
    context={
        "signals_path": "data/signals/latest.json",
        "canonical_items_path": "data/canonical-items/latest.json",
        "artifact_dir": "data/agentic",
    },
)
```

The returned result should be structured:

```python
{
    "status": "ok",
    "messages": [...],
    "final_text": "...",
    "tool_calls": [...],
    "artifact_paths": [...],
    "usage": {...},
    "errors": [],
}
```

The component should also expose a small CLI later, but the component API is the primary interface.

## Agent Loop

`AgenticCore.run` should:

1. load provider and tool configuration
2. normalize incoming messages
3. send messages and tool schemas to the provider
4. detect model-requested tool calls
5. execute registered tools with validated arguments
6. append tool results back into the conversation
7. repeat until the model returns a final answer or `max_turns` is reached
8. return a structured `RunResult`

The first version should keep the loop single-agent and single-threaded. Multi-agent delegation, background workers, and durable conversation storage are out of scope.

## Provider Adapter

The first provider should be OpenAI-compatible:

```yaml
provider:
  type: openai_compatible
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_COMPATIBLE_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5
```

The adapter should support:

- chat-style messages
- tool/function schemas
- model-requested tool calls
- timeout configuration
- basic usage metadata when available
- clear error messages for missing API keys, HTTP failures, unsupported response shapes, and max-turn exhaustion

The adapter boundary should keep provider-specific response formats out of the core loop.

## Tool Registry

Tools should be registered with:

- stable name
- description
- JSON schema for arguments
- handler function
- enabled/disabled state from config

Initial project tools:

```text
read_signals
  Reads data/signals/latest.json or a provided signals path.

read_canonical_items
  Reads data/canonical-items/latest.json or a provided canonical items path.

write_agentic_artifact
  Writes final agentic output to data/agentic/latest.json and optionally latest.md.
```

Tool handlers must be narrow and explicit. They should not mutate source configuration, fetch new external data, or execute arbitrary shell commands.

## Web Workbench

The workbench is local-only and intended for development.

Runtime:

```text
FastAPI on 127.0.0.1
```

Expected first-version UI:

- chat panel for multi-turn conversation
- provider configuration form for provider type, base URL, and model
- API token status indicator showing configured or missing, never the token value
- tool enable/disable controls
- button to load current `data/signals/latest.json`
- tool call log panel
- final output panel
- artifact path display after save

The workbench should call the same `AgenticCore` component used by non-UI callers. It must not duplicate the agent loop.

## Configuration

Configuration is loaded in this order:

1. `config/agentic-core.example.yml`
2. optional gitignored `config/agentic-core.local.yml`
3. `.env` values for provider-specific API keys

`.env.example` should document provider-specific tokens:

```env
OPENAI_API_KEY=
OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
DEEPSEEK_API_KEY=
OPENROUTER_API_KEY=
MOONSHOT_AI_LLM_API_KEY=
```

Saved configurations derive their API key variable from the entered config name
by uppercasing it, replacing non-alphanumeric characters with underscores, and
appending `_LLM_API_KEY`. For example, `Moonshot AI` uses
`MOONSHOT_AI_LLM_API_KEY`, and `Work DeepSeek` uses
`WORK_DEEPSEEK_LLM_API_KEY`.

Example YAML should document non-secret runtime behavior and provider profiles:

```yaml
provider:
  type: openai_compatible
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_COMPATIBLE_BASE_URL
  default_base_url: https://api.openai.com/v1
  model: gpt-5

provider_profiles:
  active: openai
  items:
    openai:
      label: OpenAI
      type: openai_compatible
      api_key_env: OPENAI_API_KEY
      base_url: https://api.openai.com/v1
      model: gpt-5
    deepseek:
      label: DeepSeek
      type: openai_compatible
      api_key_env: DEEPSEEK_API_KEY
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat
    openrouter:
      label: OpenRouter
      type: openai_compatible
      api_key_env: OPENROUTER_API_KEY
      base_url: https://openrouter.ai/api/v1
      model: openai/gpt-4.1
    custom:
      label: Custom
      type: openai_compatible
      api_key_env: CUSTOM_LLM_API_KEY
      base_url: https://api.openai.com/v1
      model: gpt-5
```

The workbench separates saved configurations from provider templates. Selecting
a saved configuration activates an existing profile. Selecting `New
Configuration` plus a provider template creates or updates a named local
profile:

```yaml
provider_profiles:
  active: work_deepseek
  items:
    work_deepseek:
      label: Work DeepSeek
      template: deepseek
      type: openai_compatible
      api_key_env: WORK_DEEPSEEK_LLM_API_KEY
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat
```

The remaining example YAML keeps the shared agent, tool, and path settings:

```yaml
agent:
  system_prompt: |
    You are the Founder Intelligence Agentic Core. Use tools when they help
    ground the analysis in local project artifacts. Preserve uncertainty.
  max_turns: 8
  temperature: 0.2
  timeout_seconds: 60

tools:
  read_signals:
    enabled: true
  read_canonical_items:
    enabled: true
  write_agentic_artifact:
    enabled: true

paths:
  signals: data/signals/latest.json
  canonical_items: data/canonical-items/latest.json
  artifact_dir: data/agentic
```

## Security and Local-Only Boundary

The workbench should bind to `127.0.0.1` by default.

API tokens should only be read from environment variables loaded from `.env`. The UI can report whether an expected token is configured, but it must not return token values to the browser.

No first-version tool should execute arbitrary code, run shell commands, mutate `config/`, or make external network requests other than the configured LLM provider call.

## Error Handling

The core should return structured errors instead of crashing where practical:

- missing config file
- invalid YAML
- missing API key env var
- unsupported provider type
- disabled or unknown tool requested by model
- invalid tool arguments
- provider timeout
- provider HTTP error
- max turns reached

The workbench should surface these errors in the UI without exposing secrets.

## Testing Strategy

Implementation should include tests for:

- config loading with `.env` and YAML
- provider adapter request shaping with a fake provider
- tool registry enable/disable behavior
- tool argument validation
- agent loop with one fake tool call
- max-turn handling
- artifact writing
- FastAPI endpoints using a fake provider

Tests should not require real API credentials.

## Integration With Current Demo

The current Ruby pipeline remains the source of deterministic artifacts.

The first useful agentic workflow is:

```text
ruby src/build_signals.rb ...
python -m web_workbench.app
open local workbench
ask Agentic Core to analyze current signals
save output to data/agentic/latest.json and latest.md
```

Later, a CLI can support:

```bash
python -m agentic_core.run --config config/agentic-core.yml --prompt "Analyze today's founder signals"
```

Ruby integration can call the Python CLI or local HTTP endpoint later if needed. Direct cross-language embedding is not required for the first version.

## Future Extensions

Possible future additions:

- Anthropic and Gemini provider adapters
- OpenAI Agents SDK runtime adapter
- LangGraph runtime adapter for long-running stateful workflows
- MCP tool adapter once runnable MCP sources exist
- persistent conversation history
- artifact viewer inside the existing dashboard
- scheduler integration
- human approval gates for external side-effect tools

These should be added only after the first local component proves useful against the current signal pipeline.
