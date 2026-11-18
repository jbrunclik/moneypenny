---
paths:
  - "evals/**"
---

# Evals

- `make eval` runs agent-behavior cases against the live API — it costs money. Always report the run's USD cost (the harness prints it); a simple case costs about $0.03 and deep-research cases far more (145 cases, Nov 18 2026; full-run cost not re-measured yet - TODO), so run the cases you need with `--only`, or `make eval-smoke` (~$1) after a change to `src/agent/`. Every run appends a line to the tracked `evals/history.jsonl`: commit it with the change it measured.
- Web is **canned by default** (Nov 18 2026): a case's `web:` block answers searches and fetches (no block = no results); only `web: live` cases search for real, on purpose. Capture real pages once with `evals/capture_web.py`. Long-context cases borrow a shared synthetic chat (`history_from:`, `evals/fixtures/chats/`) - synthetic people and data only, the repo is public.
- Live web search runs on `ddgs` only: `isolate_environment` blanks the metered provider keys (`EVAL_BLANKED_SEARCH_KEYS`), so evals never spend the family's shared Brave/Tavily/Exa/Linkup quota. Add a new metered provider's key there (a test enforces the count).
- Integration tools run against in-memory fakes in [evals/fakes.py](../../evals/fakes.py) (a case opts in with `integrations:`); they replace the HTTP/client seam, not the tool.
- The judge and the agent are noisy: run a case several times (`--only <id>`) before concluding a change helped.
- See [docs/testing/evals.md](../../docs/testing/evals.md).
