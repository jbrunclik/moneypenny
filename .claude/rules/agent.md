---
paths:
  - "src/agent/**"
  - "src/config.py"
---

# Agent conventions

- **Add a new tool**: create a file in [src/agent/tools/](../../src/agent/tools/), add the `@tool` decorator, and register it in [tools/__init__.py](../../src/agent/tools/__init__.py). See [docs/features/agents.md](../../docs/features/agents.md#adding-a-new-tool).
- **Change available models**: edit the `MODELS` dict in [src/config.py](../../src/config.py).
- **Browser tool**: `make browser-setup` installs Playwright + Chromium. Enabled by default (`BROWSER_ENABLED=true`); set `BROWSER_ENABLED=false` in `.env` to disable. See [docs/features/agents.md](../../docs/features/agents.md).
- **Key files**: `agent.py`, `graph.py` (nodes, routing, self-correction), `prompts.py`, `content.py`, `history.py`.
