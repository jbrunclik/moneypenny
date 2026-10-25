---
description: Run the regular product review - errors, agents, cost, quality, code health - and report findings
---

Run the regular review: $ARGUMENTS (default: weekly; "monthly" for the full
checklist).

Follow [docs/regular-review.md](../../docs/regular-review.md) - its rules
apply: measure before concluding, production read-only, no conversation
content in the report, no infrastructure names in anything tracked.

1. **Access.** Production logs and the database need SSH to the production
   host. If this session has no consent for read-only production access yet,
   ask for it once, up front; without it, review what the admin page API and
   the repo show and say what was skipped.
2. **Collect.** Work through the sections for the cadence (weekly: 1-4,
   monthly: 1-6). Gather the numbers first, then look for causes; run
   independent queries in parallel.
3. **Compare.** Find the previous report (ask if it isn't in the
   conversation) and state each number's trend.
4. **Report** in the template from the doc, most important finding first,
   each with a proposed action. Propose; don't fix - fixes are separate work
   the maintainer agrees to.
5. **TODO.** Offer the findings that need follow-up as `TODO.md` entries
   (dated, with the measurement); add them once the maintainer agrees.
