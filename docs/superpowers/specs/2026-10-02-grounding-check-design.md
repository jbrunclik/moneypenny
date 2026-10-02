# Grounding Check - Design

Status: approved design, Oct 2 2026.

## Problem

The Sep 2026 conversation sweep's most common correction was stale or invented
specifics ("your data is old", "you're making it up"). On turns that did research,
the model mixes shop names, prices and place names from its own knowledge into
verified results without labelling them. Two prompt-level fixes (Sep 30 2026) had no
measured effect: `GROUNDING_DIRECTIVE` appended to every web result and an always-on
"unverified specifics" rule. `skill_product_where_to_buy` still passes 1/5. On Oct 2
2026 the judge flagged unconfirmed shops ("VeloRama", "Bazoš") presented as fact.
Rules the model is asked to follow have not worked, so this check runs after the
answer, outside the model.

## Goal and success criteria

After a turn that used web tools, a cheap verifier compares the answer with the
turn's sources. Concrete specifics the sources do not support get listed in a short
note appended to the answer.

- `skill_product_where_to_buy` passes at least 4/5 runs (baseline 1/5).
- No spurious note on well-grounded answers. The new precision case
  `cz_grounded_no_note` passes, and the existing web cases do not gain notes.
- The full eval suite pass rate is unchanged.
- Added cost is about $0.004 per web turn. Added latency is about 1-3 s before
  `done`, bounded by a timeout.

## Non-goals

- Turns with no web tools. Answers from memory without any lookup, such as news
  asked with no search, are a separate failure.
- Rewriting the answer, inline per-claim markers, any new UI or SSE event type.

## Placement and trigger

New module `src/agent/grounding_check.py`:

- `find_unverified(answer, result_messages) -> GroundingResult` - decides whether to
  run, collects sources, calls the verifier, and returns the flagged items plus usage.
- `append_unverified_note(answer, items, language) -> str` - formats the note.

It is called in the agent layer, so evals see exactly what users see:

- at the end of `ChatAgent.chat_batch`, after `final_response_text`;
- in the stream path just before the `final` event is yielded (`stream_events.py`).

Autonomous agents run through `ChatAgent` and get it too. The save path
(`save_message_to_db`) is deliberately not the hook: evals call `chat_batch`
directly and would not see the note.

The check runs only when all of these hold:

- the turn has at least one successful result from a web tool (`research`,
  `web_search`, `fetch_url`, `browser`);
- the answer text is non-empty;
- the turn was not stopped by the user (`stop_reason` unset).

All other turns skip it at zero cost.

**Sources** are the text of those web tool results as the model saw them. They are
taken from the most recent result backwards, up to `GROUNDING_CHECK_MAX_SOURCE_CHARS`
(default 60000), since later results usually matter most.

**Streaming:** tokens stream as today. The check runs after the last token, so
`done` arrives about 1-3 s later. `done.content` already replaces the streamed text
on the client, so the note appears there with no frontend change.

## Verifier

- Model: `GROUNDING_CHECK_MODEL`, default `gemini-3.5-flash-lite`, the newest text
  Flash-Lite model the API lists in Oct 2026. Temperature 0, no thinking, built like
  `title.py`. Its price ($0.30 input / $0.03 cached / $2.50 output per 1M tokens)
  goes into the pricing table only, not the user-selectable model list. If Lite
  proves too imprecise, `GROUNDING_CHECK_MODEL=gemini-3.8-flash` switches it without
  a code change.
- Output: `with_structured_output(GroundingVerdict)`, as the memory defrag job does.
  The schema is `unsupported: list[UnverifiedItem]`. Each item has `text` (the
  specific exactly as written in the answer) and `kind` (`shop | place | price |
  hours | date | figure | other`).
- Prompt (precision first):
  - Flag only concrete, checkable specifics in the answer that the sources do not
    contain or that they contradict: names of shops, places, venues, products and
    people, and prices, opening hours, dates and figures.
  - Never flag general knowledge, advice, the answer's own reasoning, or items the
    answer already labels as unverified or estimated.
  - When unsure, do not flag.
- At most `GROUNDING_CHECK_MAX_ITEMS` (default 5) items are kept.
- Hard timeout `GROUNDING_CHECK_TIMEOUT_SECONDS` (default 8).
- Usage (input, output and cached tokens, priced at the verifier model's rates) is
  added to the turn's `usage_info`, so `message_costs` stays accurate.

**Failure handling:** fail open. On a timeout, API error or schema error the check
logs a warning and returns the answer unchanged.

**Telemetry:** one log line per check with `flagged_count`, `kinds`, `source_chars`
and `duration_ms`. Prod logs then show the share of web turns flagged and what gets
caught.

## The note

The note is appended after a blank line as one italic line, in the answer's language
(`detect_response_language`). Czech gets the Czech template, every other language the
English one:

- cs: `_Neověřeno ve zdrojích, které jsem teď četl: VeloRama, Bazoš, 12 990 Kč._`
- en: `_Not confirmed in the sources I read for this answer: VeloRama, Bazoš, 12 990 CZK._`

Items appear as written in the answer, de-duplicated, at most 5.

The note becomes part of the saved message content. Later turns see it in history,
so the model knows those items were unverified. Search, copy and export include it,
and a reload shows the same text. Item kinds are logged only and never shown.

## Configuration

New entries in `src/config.py`, `.env.example` and the docs:

- `GROUNDING_CHECK_ENABLED` (default true) - kill switch.
- `GROUNDING_CHECK_MODEL` (default `gemini-3.5-flash-lite`).
- `GROUNDING_CHECK_MAX_SOURCE_CHARS` (default 60000).
- `GROUNDING_CHECK_MAX_ITEMS` (default 5).
- `GROUNDING_CHECK_TIMEOUT_SECONDS` (default 8).

## Testing

- Unit tests (`tests/unit/test_grounding_check.py`, fake LLM):
  - trigger rules: web tool present, empty answer, stopped turn, non-web tools only;
  - source collection and the char cap (most recent kept);
  - note formatting in cs and en, de-duplication, the item cap;
  - fail-open on timeout, exception and bad schema;
  - verifier usage added to `usage_info`.
- Hook tests: `chat_batch` and the stream `final` event append the note when the
  verifier flags items and leave the answer untouched when it does not. The existing
  `chat_batch` / `stream_chat_events` mock shapes stay the same.
- Evals, before and after:
  - `skill_product_where_to_buy` over 5 runs;
  - the new `cz_grounded_no_note` precision case;
  - a spot-check of `cz_local_lookup`, `web_lookup_cited` and the trip cases for
    spurious notes;
  - the full suite.

  Report the eval cost and the verifier's per-turn cost.

## Rollout

Deploy with the check enabled and watch the telemetry for a week. Then decide
whether the default model, the source cap or the prompt needs tuning.
