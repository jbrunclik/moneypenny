---
description: Add an agent tool - the full registration checklist, schema guard, tests, docs
---

Add an agent tool: $ARGUMENTS

A tool is registered in several places today (B8 will collapse them into one
registry). Follow the checklist in `docs/features/agent-tools.md`
("Adding a New Tool") step by step - registering in `tools/__init__.py`
alone is not enough, and `tests/unit/test_tool_display.py` fails the build
when display metadata is missing.

1. **Design.** One tool per job; arguments the model can fill from the
   conversation. Put efficiency and next-step hints in the tool RESULT, not
   the system prompt (measured: prompt-level guidance is ignored).
2. **Test first.** `tests/unit/test_<tool>.py` - the tool's behavior through
   its seams (HTTP client, DB), plus a schema guard that every parameter has a
   concrete type (see `test_garmin_workout_tool.py::TestToolSchema`): a
   type-less parameter breaks every chat request, not just this tool.
3. **Implement** in `src/agent/tools/<tool>.py` with `@tool`. The docstring is
   the model's description: a summary plus an `Args:` line per parameter.
   Failures go through the shared tool-error shape (B5). Outbound calls have a
   timeout (S5); URLs from the model pass `validate_public_url` (S3).
4. **Register** everywhere the checklist lists (backend, `AgentEditor.ts`,
   prompt enhancer, icons, config and `.env.example` if configurable).
5. **Evals** if it changes agent behavior: a case in `evals/cases/`, run with
   `--only <id>` a few times; report the cost.
6. **Docs.** The tools table in `docs/features/agent-tools.md`, plus a
   `docs/features/<integration>.md` page for an external service.
7. **Verify.** `make lint` and `make test` (add `make test-all` if the UI
   changed), exit codes checked.
