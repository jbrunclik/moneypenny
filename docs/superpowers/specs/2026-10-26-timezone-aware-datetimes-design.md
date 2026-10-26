# Timezone-aware datetimes (UTC storage)

Decided Oct 26 2026: all of the planner's recommended defaults accepted - one `APP_TIMEZONE` (Europe/Prague) for day boundaries, fixed-width `...+00:00` UTC storage, caches purged, write-only columns left as is, ruff DTZ enabled in the switch step (2b), the repeated DST hour resolved by insertion order, one sync refresh per conversation accepted, the execution mode (plain migration vs online batch) chosen from a dry run on a backup copy. Steps ship at least a day apart. The production host has been on Europe/Prague since at least Dec 14 2025 (verify older rows from the paired UTC/local histogram); the UTC-naive cutoff is the ce810114 deploy on Jun 10 2026, ~22:00 local.

