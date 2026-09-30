# Skills: on-demand instruction packs - Design

Status: approved approach, Sep 30 2026. Implements TODO "Next up" #1 (built-in skills; user-authored skills stay a TODO item).

## Problem

All agent guidance lives in the always-on system prompt (`src/agent/prompt_texts/`; the tool
prompt alone is ~30k chars, ~7.5k tokens). Much of it is recipe-level how-to that only a few
turns need: office/PDF generation, browser tactics, the weekly planning session. Every turn
carries it, and every new how-to makes the prompt longer. Measured on production (30 days to
Sep 30 2026): 5,243 turns; `execute_code` in 82 rounds, `browser` in 81, planning sessions rare.

## Goal and success criteria

A skill mechanism like Anthropic Agent Skills: an always-on index of short entries, a
`load_skill` tool that returns a skill's full instructions on demand.

- The four first skills (below) load when a turn needs them: **trigger rate ≥ 90%** on the
  should-trigger eval cases, and **no loads** on the should-not-trigger cases.
- The existing eval suite does not regress (pass count and rubric scores within run-to-run
  noise, judged on two runs before and two after).
- The context cache keeps hitting: the index is byte-stable and the tool list does not change
  when a skill loads.
- If triggering misses the bar, the fallback ships instead: the mechanism with the four
  recipes left always-on (no regression risk), and a TODO note with the measured rates.

Non-goals: user-authored skills (TODO), bundled scripts/resources per skill, skills that add
tools, re-attaching skills after compaction.

## Evidence behind the design

Research summary (sources in the Sep 30 2026 conversation; key ones):
- Anthropic, Google ADK (`SkillToolset`) and LangChain Deep Agents converge on the same
  three levels: metadata always in context → body loaded on demand → bundled files. The
  SKILL.md format is an open standard (agentskills.io).
- Triggering is the weak point: Vercel measured skills never invoked in 56% of eval cases
  with passive descriptions; explicit/directive wording raised invocation to 95%+.
  Directive "ALWAYS load X before Y" phrasing beat passive "Use when…" by a large margin in
  a 650-trial study. Trigger rate falls as the number of skills grows.
- Gemini-specific: ADK reports empty replies right after `load_skill` unless the prompt
  says loading a skill does not end the turn.
- A skill body returned as a tool result lands after the cached prefix - it does not break
  the context cache. Changing the tool list or the index would.
- No controlled study shows that moving niche guidance out of a ~30k-char prompt helps; one
  (Vercel) shows always-on docs can beat on-demand. Hence the eval gate and the fallback.

## Design

### 1. Skill files

`src/agent/skills/<name>/SKILL.md`, agentskills.io-compatible frontmatter:

```markdown
---
name: office-documents
description: Word, PowerPoint and Excel files (.docx/.pptx/.xlsx) - structure, styles, formatting, formulas. Load BEFORE writing any code that creates one.
---
<body: the recipe, markdown>
```

- `name`: lowercase-hyphenated, matches the directory, ≤ 64 chars.
- `description`: ≤ 300 chars (our index budget, stricter than the standard's 1,024), third
  person, says what it covers and a directive "Load BEFORE …" trigger.
- Body: ≤ `SKILL_MAX_BODY_CHARS` (12,000 ≈ 3k tokens), plain markdown, no templating
  (no `.format()` braces pitfalls - bodies are returned verbatim).

A loader (`src/agent/skills.py`) reads all skills once at import, validates frontmatter and
limits, and exposes `list_skills() -> list[Skill]` and `get_skill(name) -> Skill | None`.
Invalid skill files fail loudly at startup (and in a unit test), not at call time.

### 2. The index (always-on)

Generated from the frontmatter in a fixed order (sorted by name) and appended to the tools
prompt as its own section:

```
# Skills
Skills are detailed instructions for specific tasks. When a task matches a skill below,
ALWAYS call load_skill(name) FIRST, before doing the task - even if you think you know how.
Loading a skill does not finish your turn: read it, then continue with the task in the same
turn.
- office-documents: <description>
- ...
```

Byte-stable across requests (no per-request content), so it stays in the cached prefix.

### 3. `load_skill` tool

`load_skill(name: str) -> str` (new `src/agent/tools/skills.py`):
- Returns the body framed with a header (`Skill: <name>` + "Follow these instructions for
  the current task.").
- Unknown name → error listing the valid names (self-correction, not retriable noise).
- Loading a skill already loaded in this turn returns a short "already loaded above" note
  (checked against the turn's messages is overkill - a per-request set keyed by request id
  in the tool-results store is enough; best effort).
- Always bound (interactive and autonomous) and in `ALWAYS_SAFE_TOOLS`: read-only, repo
  content. Full new-tool checklist from docs/features/agent-tools.md ("Adding a new tool"):
  `TOOL_METADATA`, display label/icon, agent editor and prompt-enhancer lists,
  `test_tool_display.py`.
- Not an extract-only tool: the model must see the result.

### 4. What moves (the split rule)

**Stays always-on:** anything that decides *whether* to use a tool (selection rules), safety
rules, and the 1-2 line tool summaries. **Moves:** recipe-level *how to do it well*.

| Skill | Moves out of | Stays always-on |
|---|---|---|
| `office-documents` | "Office files" bullets in the Code Execution section | "for Word/PowerPoint/Excel produce the real format via execute_code" (one line) |
| `pdf-documents` | fpdf2 + DejaVu non-ASCII recipe and example | "PDFs via execute_code" (one line) |
| `browser-tactics` | cookie banners, selector strategy, turn budget, batching tactics | browser summary + when to use it vs fetch_url, never enter credentials |
| `weekly-planning` | "Weekly Strategic Planning" section of the productivity prompt | the trigger words ("review", "planning session") in the index entry |

The `execute_code` / `browser` tool docstrings get a matching one-line pointer ("For
Word/PowerPoint/Excel output, load_skill('office-documents') first"), so the trigger also
rides on the tool description the model reads when it picks the tool.

Image-generation guidance stays: it is mostly selection rules (when to edit vs generate,
which history image) and splitting it would weaken selection.

### 5. Eval gate

1. Baseline: `make eval` twice on main before the move; record pass counts, rubric scores,
   cost.
2. New cases (`evals/cases/skill_*.yaml`):
   - Should trigger (`required_tools: [load_skill]` + a rubric on the outcome): "Make me a
     Word document with …", "Turn this table into an Excel sheet with totals", "PDF of this
     Czech text", "Let's do my weekly planning session", "Log in to <site> and check …"
     (browser, with fakes if needed).
   - Should not trigger (`forbidden_tools: [load_skill]`): a quick calculation via
     execute_code, a plain web question, a Todoist task add, a chart request.
3. After the move: `make eval` twice; new cases run 3× each (`--only`).
4. Decision: merge if every should-trigger case loads its skill in ≥ 90% of runs (≥ 3/3 or
   5/5 where re-run), should-not cases never load, and the existing suite holds. Otherwise
   try one round of index/description wording fixes, then fall back (§ Goal).
5. Report the USD cost of every run (expected ≈ $3 total).

## Error handling

- Skill file missing/invalid at startup → import-time error naming the file (CI catches it).
- Unknown skill name → tool error listing valid names.
- Body over the limit → startup validation error (keeps the per-load cost bounded).

## Testing

- Unit: loader parses/validates (name/dir match, description/body limits, sorted index,
  byte-stable across calls); `load_skill` returns the body / errors on unknown name; index
  section present in the tools prompt; every skill referenced in a docstring pointer
  exists; the moved recipes are no longer in the always-on prompt (and the one-line
  pointers are).
- Tool checklist tests (`test_tool_display.py`, permissions) cover the new tool.
- Evals as above (live API; costs reported).

## Rollout

Two commits on a branch: (1) mechanism + skills with content still duplicated always-on
(no behaviour change, safe to ship); (2) the move, merged only after the eval gate.
User-authored skills are added to TODO.md (per-user DB rows + Data-page UI, same loader
interface).
