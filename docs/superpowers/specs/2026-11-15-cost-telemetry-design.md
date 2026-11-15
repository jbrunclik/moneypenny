# Cost telemetry: per-call cache use, prefix sharing, side-call spend

Date: 2026-11-15. Size: small change. Status: approach agreed in chat
(telemetry first, then decide), design for review.

## Why

The cheapest levers on the per-turn cost (Hydrogen $0.071 a chat turn, 52%
of input cached, Nov 8-15 2026) can backfire, and today's data cannot tell:

- **Per-user tool sets** (bind Todoist/Calendar/Garmin/Rouvy only when
  connected: -1.2 to -4k tokens a call for some users) split the one fixed
  prefix the four users share. Gemini 4 has implicit caching only (Hydrogen
  and Carbon list no `createCachedContent`, checked Nov 15 2026), so a turn
  may be cached thanks to another user's recent turn. Splitting may cost more
  in misses than it saves. `message_costs` keeps cached tokens per turn, not
  per call, and nothing records which prefix was sent or when it was last
  sent.
- **Side calls** (titles, program/instruction reviews, AI assist, compaction,
  memory review and defrag) never reach `message_costs`: their spend, and
  whether lowering their thinking level is worth it, is unknown.

The user: "we need to implement better telemetry first and then see";
quality, speed and the memories as they are must not suffer.

## Goals / non-goals / anti-goals

- Goal: a week of data answering (1) cache hit rate against the gap since
  the same prefix was last sent, (2) how often a turn's cache comes from
  another user's call, (3) first call vs later rounds, (4) side-call spend
  by feature and model.
- Non-goal: any change to what the model sees (per-user tools, compact
  memories, thinking levels) - decided from this data later.
- Anti-goal: telemetry that slows a turn noticeably (a write per model call
  is fine; nothing on the critical path waits on the network); a migration
  where a JSON key does.

## Approaches

- **Picked: per-call records in `turn_timing`, one shared "last sent" record
  per prefix, a small side-costs table.**
- Per-call rows in a new table: richer queries, but a migration and a write
  path for data that fits the existing JSON column.
- Logs only: no migration, but joins to turns and costs become journal
  parsing; the journal keeps ~45 h on the production host for some units.

## Design

**Per model call** (chat turns, `chat_node._invoke_model` via `ModelTiming`):
`turn_timing.calls` = a list, one entry per call, with `input`, `cached`,
`output` tokens, `ms`, `prefix` (8 hex: a hash of the model, the static
system prompt and the bound tool declarations, in the order sent), `gap_s`
(seconds since that prefix was last sent by anyone; null the first time)
and `same_user` (whether that last send was this user's).

**Last sent per prefix**: the kv store (system user, namespace
`prefix-cache`), key = prefix hash, value = time and user id; read then
written per call. Shared by all workers. Old keys need no cleanup (a few
dozen distinct prefixes).

**Side calls**: a `side_costs` table (migration): `created_at`, `user_id`
(nullable), `feature` (`title`, `program_review`, `instructions_review`,
`ai_assist`, `compaction`, `memory_review`, `memory_defrag`, `deep_research`
writer/subagents if not already in `message_costs`), `model`,
`input_tokens`, `cached_input_tokens`, `output_tokens`, `cost_usd`. One
helper records a side call from its response's usage; each feature's call
site uses it. Failures to record are logged, never raised.

**Instrumented by itself.** Regular review: a cache section (hit rate by
`gap_s` bucket and by `same_user`, first call vs rounds) and side costs per
feature per week. TODO: decide per-user tools, compact memories and
side-call thinking ~Nov 23 2026 from a week of data.

## Left to the builder

The exact hash input (stable across workers and restarts), the gap buckets
the review uses, which side-call sites exist (grep `chat_model(` and
`generate_content`), and whether the admin page shows side costs now or
later.
