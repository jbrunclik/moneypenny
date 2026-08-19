# Agent Behavior Evals

Golden-case eval harness for agent quality: run real conversations through
`ChatAgent`, check tool behavior deterministically, and score answers with an
LLM judge. Lives in [evals/](../../evals/).

## When to run

Run `make eval` **before and after** changing:
- the system prompt or tool descriptions ([prompts.py](../../src/agent/prompts.py))
- the graph flow ([graph.py](../../src/agent/graph.py))
- tool registration/bindings
- the default model or thinking settings

Compare pass rates and per-case reasoning. The harness is **informational** —
it hits the live Gemini API (a few cents per run) and is deliberately NOT part
of CI or `make test`.

## How it works

1. Each YAML file in `evals/cases/` is one single-turn case.
2. `evals/run.py` creates an isolated temp database (migrations apply
   automatically) and an eval user, then runs each case through
   `ChatAgent.chat_batch` with the production `DEFAULT_MODEL`.
3. Deterministic checks run first: `required_tools` (any-of), `forbidden_tools`,
   `max_tool_rounds`.
4. An LLM judge (`EVAL_JUDGE_MODEL`, default Gemini Pro) scores the response
   1–5 against the case rubric and decides pass/fail.
5. Results print as a summary and land in `evals/results/<timestamp>.json`
   (gitignored).

A case passes only if the judge passes it AND no deterministic check failed.
Cases with unmet `requires` (e.g. `code_sandbox` without Docker) are skipped.

## Case format

```yaml
id: web_lookup_cited
description: Current-fact question requires a web tool and a citation
user: What is the current price of Bitcoin in USD?
requires: [code_sandbox]        # optional: skip when unavailable
expect:
  rubric: >                     # required: what the judge grades against
    The answer gives a concrete price, acknowledges fluctuation, and cites
    at least one source.
  required_tools: [research, web_search]   # optional, any-of
  forbidden_tools: [delegate_task]         # optional
  max_tool_rounds: 4                       # optional, 0 = no limit
```

Authoring tips:
- Verify rubric numbers yourself first (the first harness run caught a wrong
  expected value in a rubric, not in the agent).
- `required_tools` is any-of — list all acceptable tools for the behavior.
- Keep failing cases that represent real improvement targets; the harness is
  a baseline tracker, not a green wall. Known-failing baselines (Aug 2026):
  `research_multi_source` (round overrun), `web_lookup_cited` (citation
  adherence).

## Commands

```bash
make eval                                  # all cases
.venv/bin/python evals/run.py --only code_exec   # one case
```

## Key files

- [evals/run.py](../../evals/run.py) - runner, case loading, judge
- [evals/cases/](../../evals/cases/) - golden cases
- [tests/unit/test_eval_harness.py](../../tests/unit/test_eval_harness.py) - unit tests for the pure pieces
- [config.py](../../src/config.py) - `EVAL_JUDGE_MODEL`
