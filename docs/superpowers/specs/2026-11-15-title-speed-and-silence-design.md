# A new chat's title stops delaying the reply; model-call silences are measured

Date: 2026-11-15. Size: small change. Status: approved approach (title option 1,
silence recorded first), design for review.

## Why

Faster replies (Nov 15 2026 audit, "Reply speed"). On a new chat the `done`
event waits for the title: it carries it, and `save_message_to_db` generates it
with Hydrogen at the API-default (high) thinking, default retries and the 180 s
timeout. Measured Nov 15: 3.3 / 4.9 / 17.3 s; the reply is on screen but the
turn still shows as running. Flash-Lite gave equally good titles in 0.5-0.7 s
(Hydrogen at low thinking: 1.7-3.2 s).

The audit also asked for a stall watchdog (abort a model call silent for
~30-45 s). The journal shows no model-call timeout in 30 days, so the silence
is measured first and the watchdog built only if the numbers show stalls.

## Goals / non-goals / anti-goals

- Goal: a new chat's `done` no longer waits seconds for its title.
- Goal: each turn records its longest silence inside a model call, so the
  watchdog's need and threshold come from data.
- Non-goal: the title after `done` (a `title` stream event or the sync) -
  parked in TODO; the freshness gate in parallel; batch mode (35% of turns,
  one person; left as it is until we know why).
- Anti-goal: worse titles; a title failure that breaks or delays the save
  (today's contract: None leaves the default title and the next message retries).

## Approaches

1. **Picked: Flash-Lite in place.** `TITLE_GENERATION_MODEL` = Flash-Lite, a
   short timeout, no retries; still inside the save, so `done` still carries it.
2. Title after `done` (stream event or the next sync, up to 60 s) - zero wait,
   but client, journal and resume changes for ~0.6 s. TODO.
3. Title from the question at the turn's start - zero wait, but blind to the
   reply ("ahoj" gives a weak title).

Watchdog: record first (picked) vs build now (a helper thread per call to
abort a blocked read; no evidence yet).

## Design

**Title.**
- `TITLE_GENERATION_MODEL` default `gemini-3.5-flash-lite`;
  `TITLE_GENERATION_TIMEOUT_SECONDS` = 10; no retries (`max_retries=0` via
  `chat_model`). Plain `Config` constants as today (not env vars), so no
  `.env` changes.
- A structured log line per title call with its duration and outcome
  ("Conversation title generated": `elapsed_ms`, `ok`), so the review sees
  the wait and the failure rate.

**Silence.**
- Per model call, the longest gap without a streamed chunk (start to first
  chunk, between chunks, last chunk to the end), counting thought chunks
  (streaming turns include thoughts). A call that streamed nothing (batch
  mode) records no silence - its wait is its whole duration, already in
  `model_ms`.
- The turn's maximum goes into `message_costs.turn_timing` as
  `max_silence_ms` (a JSON key: no migration).

**Instrumented.** Regular review: title `elapsed_ms` median/p90 and failures;
`max_silence_ms` distribution. TODO: re-measure ~Nov 22 2026 with the other
reply-speed numbers - silences over ~30 s on healthy turns decide the
watchdog and its threshold.

## Left to the builder

Where the gap is tracked (CancelOnToken already sees every chunk), the log
line's exact fields, and the tests' seams for the clock.
