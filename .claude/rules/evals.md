---
paths:
  - "evals/**"
---

# Evals

- `make eval` runs agent-behavior cases against the live API — it costs money. Always report the run's USD cost (the harness prints it); the full suite (58 cases) is roughly $1.40 (Oct 2026), and takes about 4 min on the default 4 workers.
- Web search runs on `ddgs` only: `isolate_environment` blanks the metered provider keys (`EVAL_BLANKED_SEARCH_KEYS`), so evals never spend the family's shared Brave/Tavily/Exa/Linkup quota. Add a new metered provider's key there (a test enforces the count).
- Integration tools run against in-memory fakes in [evals/fakes.py](../../evals/fakes.py) (a case opts in with `integrations:`); they replace the HTTP/client seam, not the tool.
- The judge and the agent are noisy: run a case several times (`--only <id>`) before concluding a change helped.
- See [docs/testing/evals.md](../../docs/testing/evals.md).
