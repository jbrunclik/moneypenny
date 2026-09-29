---
paths:
  - "evals/**"
---

# Evals

- `make eval` runs agent-behavior cases against the live API — it costs money. Always report the run's USD cost (the harness prints it); the full suite is roughly $0.70.
- Integration tools run against in-memory fakes in [evals/fakes.py](../../evals/fakes.py) (a case opts in with `integrations:`); they replace the HTTP/client seam, not the tool.
- The judge and the agent are noisy: run a case several times (`--only <id>`) before concluding a change helped.
- See [docs/testing/evals.md](../../docs/testing/evals.md).
