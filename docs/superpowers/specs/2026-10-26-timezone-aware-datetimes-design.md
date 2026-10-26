# Timezone-aware datetimes (UTC storage)

Decided Oct 26 2026: all of the planner's recommended defaults accepted - one `APP_TIMEZONE` (Europe/Prague) for day boundaries, fixed-width `...+00:00` UTC storage, caches purged, write-only columns left as is, ruff DTZ enabled in the switch step (2b), the repeated DST hour resolved by insertion order, one sync refresh per conversation accepted, the execution mode (plain migration vs online batch) chosen from a dry run on a backup copy. Steps ship at least a day apart. The production host has been on Europe/Prague since at least Dec 14 2025 (verify older rows from the paired UTC/local histogram); the UTC-naive cutoff is the ce810114 deploy on Jun 10 2026, ~22:00 local.

## Key findings
1. Two storage conventions already coexist: since ce810114 (2026-06-10) `src/utils/datetime_utils.py` writes
   UTC-naive for agent tables, caches, kv_store, app_settings, artifacts; conversation data stays local-naive
   (host time). Pre-June rows in the UTC-naive tables are local. The migration needs a per-column source zone
   plus a cutoff date for those tables.
2. yoyo marks a migration applied in a separate transaction from its steps - a crash in between re-runs it.
   The conversion must be per-row idempotent (only values without an offset are converted).
3. `make update` pulls, installs, THEN backs up; the agent-scheduler timer (every minute) runs
   `Database._init_db` and can apply a new migration before the backup.
4. yoyo lock timeout is 10 s with 2 non-preloaded gunicorn workers: a long migration makes the second worker
   fail to boot; old workers may write old-format rows for up to 600 s while draining.
5. Live bug today: the frontend compares timestamp strings (`state/slices/conversationOrder.ts:44,63`,
   `core/remote-merge.ts:81`), and client-made `...Z` strings get compared with server local-naive strings.
   Also planner `server_time` (routes/planner.py:307) is naive UTC that the browser parses as local.

## Steps (one deploy each, at least a day apart)
- 0 (S): deploy safety - backup before `git pull` in `_update`; timers/scripts skip pending migrations (only
  web workers apply them); configurable yoyo lock timeout. Tests for both.
- 1 (S): frontend `utils/timestamps.ts` (`toMillis`, `compareTimestamps`); fix the string comparisons above
  (fixes today's Z-vs-local ordering bug).
- 2a (S-M): `src/utils/clock.py` (utc_now, app_tz, local_today, local_day_start, local_month_bounds,
  planner_cutoff, to_api) + `src/db/models/timestamps.py` (from_db accepts naive/Z/offset -> aware UTC;
  to_db writes legacy format until app_settings flag `timestamp_storage=utc`); SQLite UDF app_local_date;
  config APP_TIMEZONE, LEGACY_TIMESTAMP_TIMEZONE. DST test tables. No behavior change.
- 2b (L, 1.5-2.5k lines): all mappers via from_db, all now via utc_now, writes/params via to_db; day
  boundaries via APP_TIMEZONE (planner 4am, spend today, agent stats, cost months, admin buckets via UDF,
  date.today(), prompts/history); API serializes with offset (OpenAPI `Timestamp` alias, format date-time);
  third-party naive values made explicit; ruff DTZ on with no baseline; AST guard banning naive
  fromisoformat/combine/strptime/localtime; contract test that every *_at has an offset; backend suite under
  TZ=Pacific/Chatham and TZ=UTC; make eval.
- 2c (optional script): online batch conversion of rows older than 3 days if the dry run is slow.
- 3 (M): yoyo data migration with a Python UDF `to_utc(value, kind)`, kinds local / utc / utc_since:<cutoff>;
  drop+recreate `sync_change_message_update` around the messages UPDATE (exact SQL from 0061); write the flag
  in the same transaction. Dry run on the latest nightly backup copy first (report per column, timing, WAL
  size), invariant checks (counts, zero naive left, offset equals tz offset, libc cross-check, ordering
  identical, app-level results identical), smoke test via make dev on the copy.
- 4 (S-M, a day later): re-run converter for stragglers, assert zero naive, drop tolerance and the flag
  branch, remove utcnow_naive/to_utc_iso, docs (database.md, conventions C3 + new rule, planner, costs).

## Biggest risks
- A missed naive datetime raises TypeError at runtime (DTZ misses fromisoformat/combine -> AST guard).
- Wrong source timezone shifts all history 1-2 h (verify from paired UTC/local rows before migrating).
- Migration duration vs 10 s yoyo lock / 30 s busy timeout / 120 s health gate.
- Old-format rows from draining workers; the migration running before the backup (step 0 fixes).

## Critical files
src/utils/datetime_utils.py, src/db/models/base.py (_init_db), src/db/models/helpers.py (planner reset,
cursors), src/db/models/*_rows.py, src/api/helpers/admin_overview.py, src/db/models/cost.py, Makefile
(_update), web/src/state/slices/conversationOrder.ts, web/src/core/remote-merge.ts,
migrations/0061_add_sync_change_log.py.
