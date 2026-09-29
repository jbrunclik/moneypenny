# Visual Regression Tests

Visual tests capture screenshots and compare against baselines pixel-by-pixel.

## When to Run Visual Tests

Run visual tests after intentional UI changes:

```bash
# Run visual tests against baselines
make test-fe-visual

# Update baselines after UI changes
make test-fe-visual-update
```

**Note**: Visual tests are intentionally excluded from `make test-fe` because they:
- Compare screenshots pixel-by-pixel and can fail due to font rendering differences
- Require baseline updates when UI changes intentionally
- Run slower than functional tests

## Per-Platform Baselines

**Visual baselines are per-platform.** Local development on macOS produces
`*-darwin.png` baselines (chromium + webkit); CI runs the suite inside the
Playwright Docker container (`mcr.microsoft.com/playwright:v<version>-jammy`,
version taken from `@playwright/test` in `web/package.json`) and compares
against the committed `*-linux.png` baselines. The CI/container runs are
**chromium-only** - webkit inside the Linux container is flaky in ways the
darwin runs are not, so Safari coverage stays local. Both sets live in
`web/tests/visual/*.visual.ts-snapshots/` and both must be regenerated
after intentional UI changes:

```bash
make test-fe-visual-update          # darwin (local)
make test-fe-visual-linux-update    # linux (Docker; used by CI)
```

The Linux run works by starting the e2e mock server on the host and
pointing the container at it via `PW_BASE_URL` (which also disables
Playwright's managed webServer - see `scripts/visual_linux.sh`). If the
Playwright version is bumped, the Docker image tag follows automatically,
but all Linux baselines must be regenerated.

**No local Docker?** Trigger the `Update Visual Baselines (Linux)`
workflow instead (`gh workflow run "Update Visual Baselines (Linux)"`).
It regenerates the baselines on a GitHub runner - the exact environment
the CI visual job uses - and uploads them as a `linux-baselines`
artifact (branch protection blocks bot pushes); download it with
`gh run download <run-id> -n linux-baselines -D web/tests/visual/`,
then commit. This is also the most
reliable option in general since it cannot drift from CI (local Docker
on Apple Silicon runs the arm64 image unless forced to amd64).

## Baseline Locations

Baselines are stored in snapshot directories:

- `web/tests/visual/chat.visual.ts-snapshots/` - Desktop chat interface
- `web/tests/visual/mobile.visual.ts-snapshots/` - Mobile/iPad layouts
- `web/tests/visual/error-ui.visual.ts-snapshots/` - Error UI
- `web/tests/visual/popups.visual.ts-snapshots/` - Popups and modals
- One `<name>.visual.ts-snapshots/` directory per spec for the rest (agents, kv-store,
  language, login, planner, quick-actions, search, sports, stream-recovery)

## When to Update Baselines

Update baselines after:
- Intentional CSS changes
- Component structure modifications
- Responsive breakpoint changes
- Design system updates

Run `make test-fe-visual-update` (darwin) and regenerate the Linux set (`/regen-baselines`
or `make test-fe-visual-linux-update`), then commit the new baseline screenshots with your UI changes.

## Troubleshooting Visual Test Failures

1. **Check diff images**: Open `web/playwright-report/index.html` to see visual diffs
2. **Verify viewport sizes**: Ensure tests run with consistent viewport dimensions
3. **Font rendering**: Font rendering differences between machines can cause false failures
4. **Ignore if expected**: If changes are intentional, update baselines
5. **Passes only on retry?** It is a state race, not pixel noise - see
   [E2E Reliability](e2e-reliability.md#visual-flakes-are-state-races-not-pixel-noise)

## Visual Test Example

```typescript
// web/tests/visual/chat.visual.ts
import { test } from '@playwright/test';

test('chat interface', async ({ page }) => {
  await page.goto('/');
  await page.click('#new-chat-btn');

  // Wait for UI to stabilize
  await page.waitForLoadState('networkidle');

  // Capture screenshot
  await expect(page).toHaveScreenshot('chat-interface.png');
});
```

## Key Files

- [web/tests/visual/](../../web/tests/visual/) - specs and `*-snapshots/` baselines
- [scripts/visual_linux.sh](../../scripts/visual_linux.sh) - Linux baselines in the Playwright Docker image
- [.github/workflows/update-visual-baselines.yml](../../.github/workflows/update-visual-baselines.yml) - CI baseline regeneration
- [.claude/commands/regen-baselines.md](../../.claude/commands/regen-baselines.md) - `/regen-baselines` workflow

## See Also

- [Testing](../testing.md) - all test commands
- [Frontend and E2E Testing](frontend.md) - Playwright setup and the mock server
- [E2E Reliability](e2e-reliability.md) - flake forensics
