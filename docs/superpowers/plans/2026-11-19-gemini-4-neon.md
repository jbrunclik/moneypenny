# Gemini 4 Neon Middle Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer Gemini 4 Neon ("Balanced") as an admin-only picker model between Hydrogen and Carbon, priced and thinking at `medium`.

**Architecture:** Config only. `Config.MODELS` drives `/api/models`, the picker and the job editor. `ADMIN_ONLY_MODELS` drives access (`src/utils/model_access.py`), and `MODEL_PRICING` drives cost rows.

**Tech Stack:** Python config + pytest; docs in Markdown.

**Spec:** `docs/superpowers/specs/2026-11-19-gemini-4-neon-design.md`

## Global Constraints

- Model id `gemini-4-neon`, name "Gemini 4 Neon", short_name "Balanced", `"thinking_level": "medium"`.
- MODELS order: hydrogen, neon, carbon. DEFAULT_MODEL stays hydrogen.
- `ADMIN_ONLY_MODELS = frozenset({"gemini-4-neon", "gemini-4-carbon"})`.
- Pricing per 1M: input 3.00, cached_input 0.15, output 15.00; no `MODEL_PRICING_CHANGES` entry.
- No What's-new announcement (admin-only). No infra details in tracked files.

## Review Focus

1. A family member's chat that stores `gemini-4-neon` (e.g. picked by an admin on a shared standing chat) must run on Hydrogen, not 400 or Neon. Pinned by `test_a_stored_neon_chat_runs_on_the_default_for_the_family`.
2. Neon priced after Dec 1 must not pick up Carbon's change. Pinned by `test_neon_has_no_dated_change`.
3. The README test fails until README names Neon ("Balanced"). Covered by the existing `test_names_every_configured_model`.
4. Tests that hard-code the model list or count (`test_schemas`, `/api/models` route tests, component tests) may break. Run the full suite and fix assertions, not behaviour.
5. Neon's medium level must come from its MODELS entry (`chat_model._model_kwargs`). Pinned by `test_neon_thinks_at_medium`.

---

### Task 1: Neon in config, tested

**Files:**
- Modify: `src/config.py` (MODELS ~L27, ADMIN_ONLY_MODELS comment + value ~L41-44, MODEL_PRICING ~L199)
- Test: `tests/unit/test_model_access.py`, `tests/unit/test_costs.py`

**Interfaces:** Produces the config values above; nothing new in code.

- [ ] **Step 1: Write the failing tests.**
  - `test_model_access.py`: fixture uses the real `Config.ADMIN_ONLY_MODELS` and patches only ADMIN_EMAILS. New tests:
    - `test_neon_sits_between_hydrogen_and_carbon`: `list(Config.MODELS) == ["gemini-4-hydrogen", "gemini-4-neon", "gemini-4-carbon"]` and `Config.MODELS["gemini-4-neon"]["short_name"] == "Balanced"`.
    - `test_neon_is_admin_only`: `not model_allowed(_FAMILY, "gemini-4-neon")` and `model_allowed(_ADMIN, "gemini-4-neon")`.
    - `test_a_stored_neon_chat_runs_on_the_default_for_the_family`: `model_for(_FAMILY, "gemini-4-neon") == Config.DEFAULT_MODEL`.
    - `test_neon_thinks_at_medium`: `Config.MODELS["gemini-4-neon"]["thinking_level"] == "medium"`.
  - `test_costs.py`: `test_neon_has_no_dated_change`: `get_model_pricing("gemini-4-neon", at=datetime(2027, 1, 2, tzinfo=UTC))` equals `{"input": 3.00, "cached_input": 0.15, "output": 15.00}`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/unit/test_model_access.py tests/unit/test_costs.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Edit `src/config.py`** with the Global Constraints values. Put a short comment on the Neon entry with the Nov 19 2026 probe numbers that justify `medium`, and update the ADMIN_ONLY_MODELS comment with Neon's rates.
- [ ] **Step 4: Run the same tests.** Expected: PASS.

### Task 2: Docs, review check, TODO re-measures

**Files:** `README.md:42`, `docs/features/admin.md:12-14`, `docs/regular-review.md` (cost section), `TODO.md`

- [ ] **Step 1:** README: "Three Gemini models per conversation: **Gemini 4 Hydrogen** ("Fast", the default), **Gemini 4 Neon** ("Balanced") and **Gemini 4 Carbon** ("Advanced")". Then run `.venv/bin/pytest tests/unit/test_readme.py -q` → PASS.
- [ ] **Step 2:** admin.md: Neon is admin-only too, with its rates.
- [ ] **Step 3:** regular-review.md: a check of Neon's cost per turn and thinking tokens against Hydrogen and Carbon (cost rows by model).
- [ ] **Step 4:** TODO.md, two dated items:
  - ~Dec 3 2026: decide whether to open Neon to the family (needs a What's-new announcement).
  - After Dec 1 2026: A/B Neon (medium) vs Carbon as `DEEP_RESEARCH_WRITER_MODEL` on a few saved runs.

### Task 3: Gate and commit

- [ ] **Step 1:** `nice -n 10 make lint > lint.log 2>&1; echo $?` → 0.
- [ ] **Step 2:** `caffeinate -i nice -n 10 make test-all E2E_PORT=8011 > test.log 2>&1; echo $?` → 0. Fix any hard-coded model-list assertions (Review Focus 4).
- [ ] **Step 3:** Stage these paths explicitly and commit `feat(models): add Gemini 4 Neon as an admin-only middle tier`.
