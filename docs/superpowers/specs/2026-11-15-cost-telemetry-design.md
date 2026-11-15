# Cost telemetry, and condensed memories in the per-turn context

Date: 2026-11-15. Size: small change. Status: approach agreed in chat
(telemetry first for the prefix levers; condensed memories now), design for
review.

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
- **The memory list** is re-sent every turn in the uncached per-turn context:
  6.1-14.3k characters per user (26-31 memories, 235-470 characters on
  average; nearly all preferences, so keeping one category in full saves
  little). Indented JSON is not the bulk - the memory text is.
- **Side calls** (titles, program/instruction reviews, AI assist, compaction,
  memory review and defrag) never reach `message_costs`: their spend, and
  whether lowering their thinking level is worth it, is unknown.

Measured Nov 8-15 2026 (Hydrogen chat turns): no tool round 33.7k input
tokens, 29% cached, $0.045; one round 66.5k, 51%, $0.063 - so a turn's first
call is mostly billed in full (nobody sent the prefix minutes before), while
an extra round is ~3/4 cached and costs ~$0.018.

The user: "we need to implement better telemetry first and then see";
memories stay (condensed in the list, the full text a lookup away); quality
and speed must not suffer much.

## Goals / non-goals / anti-goals

- Goal: a week of data answering (1) cache hit rate against the gap since
  the same prefix was last sent, (2) how often a turn's cache comes from
  another user's call, (3) first call vs later rounds, (4) side-call spend
  by feature and model.
- Goal: the per-turn memory list carries a condensed version of each
  memory (about 4-5k characters per user instead of 6-14k), the full text
  fetched when needed.
- Non-goal: per-user tool sets, keeping the prefix warm, side-call thinking
  levels - decided from this data later.
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

For the memory list (the user's idea): **picked: an LLM-written summary per
memory**, over cutting each at ~200 characters (no cost, but the detail that
matters is often at the end) and over a compact one-line format of the full
text (only ~25-35% smaller - the text is the bulk).

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

**Condensed memories.**
- `user_memories.summary` (migration, nullable): up to
  `MEMORY_SUMMARY_MAX_CHARS` (150), written by Flash-Lite
  (`MEMORY_SUMMARY_MODEL`, low cost, ~0.6 s) whenever a memory is created or
  its content changes - off the reply path (after the tool's own write; a
  failed summary leaves it null and is retried by the backfill). A one-time
  backfill writes the existing ~114. Its spend is a side cost
  (`memory_summary`). A memory shorter than the limit needs no summary (its
  text is shown).
- The per-turn list shows each memory's summary (or its text when short or
  not yet summarised) with its id, category and dates, plus `[full: N
  chars]` when condensed; the guidance says to look it up (`search_memory`,
  which also takes an id) when a detail matters, and to read the full text
  before updating a condensed memory.
- Checked before shipping with the memory eval cases (`--only`, a handful,
  under $1) against today's list.
- Telemetry: each turn records `memory_fetches` (lookups of a condensed
  memory). The summaries pay off while fewer than ~1 in 4 turns fetch; above
  that, raise the limit or show full text again.

**Instrumented by itself.** Regular review: a cache section (hit rate by
`gap_s` bucket and by `same_user`, first call vs rounds) and side costs per
feature per week. TODO: ~Nov 23 2026 decide per-user tools, keeping the prefix warm and
side-call thinking from a week of data, and check `memory_fetches` and the
per-turn input against this week's.

## Left to the builder

The exact hash input (stable across workers and restarts), the gap buckets
the review uses, which side-call sites exist (grep `chat_model(` and
`generate_content`), whether the admin page shows side costs now or
later, the summary prompt, and how `search_memory` takes an id.
