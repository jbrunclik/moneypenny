---
paths:
  - "tests/**"
  - "web/tests/**"
---

# Testing

- **E2E** — run with a bounded timeout (the Bash tool timeout; `timeout` is not on macOS). `make test-fe-e2e` rebuilds first.
- **E2E runs against the LAST `make build`, not your source.** The e2e server serves the production bundle from `static/assets/`. After ANY frontend change, `make build` before Playwright — otherwise you're debugging the previous build (symptom: your new classes/log lines never appear in the browser).
- **Zero tolerance for flaky tests** — investigate root causes, don't just re-run.
- **TDD for bug fixes**: failing test first → fix → verify → full suite.
- Visual-regression baselines are per-platform (`*-darwin.png` local, `*-linux.png` CI); regenerate Linux baselines via `/regen-baselines` after intentional UI changes. CI compares chromium only; webkit visual baselines are local-only.
- See [docs/testing.md](../../docs/testing.md).
