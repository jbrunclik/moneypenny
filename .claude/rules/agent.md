---
paths:
  - "src/agent/**"
  - "src/config.py"
---

# Agent conventions

- **Add a new tool**: follow the full checklist in [docs/features/agents.md](../../docs/features/agents.md#adding-a-new-tool) — registration in [tools/__init__.py](../../src/agent/tools/__init__.py) alone is not enough (`TOOL_METADATA`, `_CONDITIONAL_TOOLS`, the agent editor and prompt-enhancer lists all need entries; `test_tool_display.py` fails otherwise).
- **Tool results**: put efficiency/next-step directives in the tool RESULT, not the system prompt — prompt-level guidance was measured to be ignored.
- **Change available models**: edit the `MODELS` dict in [src/config.py](../../src/config.py).
- **Browser tool**: `make browser-setup` installs Playwright + Chromium. Enabled by default (`BROWSER_ENABLED=true`); set `BROWSER_ENABLED=false` in `.env` to disable. See [docs/features/agents.md](../../docs/features/agents.md).
- **Key files**: `agent.py`, `graph.py` (nodes, routing, self-correction), `prompts.py` (assembly) + `prompt_texts/` (static texts), `content.py`, `history.py`.
