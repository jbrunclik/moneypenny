---
paths:
  - "tests/**"
  - "web/tests/**"
---

# Testing

- **E2E** — always run with a timeout: `cd web && timeout 600 npx playwright test`.
- **E2E runs against the LAST `make build`, not your source.** The e2e server serves the production bundle from `static/assets/`. After ANY frontend change, `make build` before Playwright — otherwise you're debugging the previous build (symptom: your new classes/log lines never appear in the browser).
- **Zero tolerance for flaky tests** — investigate root causes, don't just re-run.
- **TDD for bug fixes**: failing test first → fix → verify → full suite.
- Visual-regression baselines are per-platform (`*-darwin.png` local, `*-linux.png` CI); regenerate Linux baselines via `/regen-baselines` after intentional UI changes.
- See [docs/testing.md](../../docs/testing.md).
