# Guided device check runner

Approved by the owner Oct 26 2026. An in-app runner of scripted layout checks
that works where no external automation reaches - the installed standalone PWA
on the owner's iPhone - and reports measured results to the admin page.

## Why

The iOS keyboard and scroll fixes (`[kbN]` rounds, see
[mobile-and-pwa.md](../../ui/mobile-and-pwa.md)) were verified by screenshots
of the kbdebug overlay: slow, and not comparable between builds. A repeatable
suite with numbers per build answers "did kb20 break anything kb19 had right?"
in two minutes.

## Flow

1. Admin page (admins only) -> **Run device checks**. The admin page closes and
   a runner card sits over the top of the real chat (fixed, so it changes no
   layout the checks measure).
2. The runner asks the server for a **fixture conversation**
   (`POST /api/admin/device-check-fixture`): a new archived conversation with
   80 scripted messages written straight to the database - no model call, no
   embedding, no push, archived so other devices' lists and sync never show it.
   The server first purges any fixture left by a crashed run (recorded in
   `device_check_fixtures`; only rows listed there are ever deleted).
3. It opens the fixture through the app's real path (`selectConversation`) and
   runs the scenarios in order, each timed and measured.
4. Steps that need the software keyboard show a big **Tap** button: iOS opens
   the keyboard only when `focus()` runs inside a real tap, so the button's
   click handler focuses the composer itself.
5. The run is saved (`POST /api/admin/device-check-runs`), the fixture purged
   (`DELETE /api/admin/device-check-fixture`, also on Stop and on failure),
   the previous conversation reopened, and a summary shown; Close returns to
   the admin page, whose **Device checks** section lists the history.

## Scenarios (data-driven registry, `web/src/core/device-checks/scenarios.ts`)

| # | Scenario | Pass when |
|---|---|---|
| 1 | Environment | always (records standalone, UA summary, viewport / visual viewport / true viewport heights, safe-area insets, `[kbN]`, app version) |
| 2 | Long conversation renders at the bottom | messages rendered; distance to bottom <= 2px; window not panned (scrollY and visualViewport.offsetTop <= 1px) |
| 3 | Send-to-top | a local user message + the batch loader (`showLoadingIndicator`, which anchors like a real send; nothing is sent): the turn's top sits at `scroll-padding-top` within 3px, the app reports it anchored, no window pan |
| 4 | Keyboard opens (tap) | after the settle window: `--keyboard-inset` equals the unified formula (`trueVH - vvH - saT`, + the standalone accessory) within 2px; composer-to-keyboard gap equals the accessory allowance within 6px; no pan; the anchored turn moved <= 4px |
| 5 | Scroll-to-bottom button, keyboard up | the button shows after scrolling away; its tap ends within 2px of the bottom; composer gap unchanged; no pan |
| 6 | Keyboard closes (tap) | inset 0, `kb-open` gone, `#app` as tall as the true viewport (1px), composer flush with the app bottom (1px), no pan |

Without a software keyboard (desktop, or Playwright) 4-6 are **skipped - no
software keyboard** without asking for a tap; a touch device whose keyboard
never appears (hardware keyboard) skips them too, while a keyboard that
appeared with a wrong inset fails. Evaluation is pure functions over a
measurement record (`evaluate.ts`), unit-tested with fake numbers; the
measuring and waiting (`measure.ts`) reuse the app's own viewport probes
(`trueViewportHeight`, `safeAreaTop` from `keyboard-viewport.ts`). The
field telemetry in `core/layout-checks.ts` (built in parallel) measures
similar invariants; the two measurement modules can merge later.

## Storage and API (admin only, `require_admin`)

- `device_check_runs`: one row per run - user, build marker, app version,
  standalone, UA summary, environment (JSON), scenarios (JSON: id, title,
  status, duration_ms, measurements, notes), pass/fail/skip counts,
  started/finished (client clock), created_at (`utc` legacy format via
  `to_db`). The newest 200 are kept (pruned on insert).
- `device_check_fixtures`: fixture conversation ids per user.
- `POST /api/admin/device-check-runs` -> 201 the stored run;
  `GET /api/admin/device-check-runs?limit=` -> newest first.
- `POST /api/admin/device-check-fixture` -> 201 `{conversation_id, message_count}`;
  `DELETE /api/admin/device-check-fixture` -> 204.

## Out of scope

Aborted runs are not stored. No hash route (the runner needs the admin page
anyway). No scheduled runs - it needs a person to tap.
