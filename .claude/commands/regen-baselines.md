---
description: Regenerate Linux visual-regression baselines via CI and commit them
---

Regenerate the Playwright **Linux** visual baselines after an intentional UI
change, then commit them. Local Docker can't produce Linux-identical renders
(and pulls hang on some machines), so we use the CI dispatch workflow.

1. **Push first.** The workflow renders from `main`, so the UI change must be
   committed and pushed before you trigger it.
2. **Trigger:** `gh workflow run update-visual-baselines.yml --ref main`
3. **Wait** (several minutes). Poll until `completed`:
   `gh run list --workflow update-visual-baselines.yml --limit 1 --json databaseId,status,conclusion`
4. **Download + apply** the artifact into the snapshot tree:
   `gh run download <run-id> -n linux-baselines -D /tmp/lb && cp -R /tmp/lb/* web/tests/visual/ && rm -rf /tmp/lb`
5. **Review honestly.** `git status web/tests/visual/` shows what changed.
   **Open a couple of the changed PNGs** to confirm the change is intended, not
   corruption or unrelated drift. A name/logo/chrome change legitimately shifts
   *dozens* of baselines because full-page snapshots include the sidebar/header.
6. **Commit + push:** `git add web/tests/visual/ && git commit -m "test(visual): regenerate baselines for <change>"`

Notes:
- The workflow only **uploads** baselines as an artifact — it does NOT auto-commit.
  Steps 4-6 are yours.
- Baselines are Git LFS objects; the push uploads them.
- If CI visual tests are red after a UI change, this is almost always the fix.
