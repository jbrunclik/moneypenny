# Grounding Check - Design

Status: approved design, Oct 2 2026; revised the same day (in-place markers replace the
end note, see Revision).

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
turn's sources. Concrete specifics the sources do not support are marked in place,
right where the answer states them.

- `skill_product_where_to_buy` passes at least 4/5 runs (baseline 1/5).
- No spurious markers on well-grounded answers. The new precision case
  `cz_grounded_no_note` passes, and the existing web cases do not gain markers.
- The full eval suite pass rate is unchanged.
- Added cost is about $0.004 per web turn. Added latency is about 1-3 s before
  `done`, bounded by a timeout.

## Non-goals

- Turns with no web tools. Answers from memory without any lookup, such as news
  asked with no search, are a separate failure.
- Rewriting the answer with a model, deleting text, any new UI or SSE event type.

## Placement and trigger

New module `src/agent/grounding_check.py`:

- `find_unverified(answer, result_messages) -> GroundingResult` - decides whether to
  run, collects sources and known facts, calls the verifier, and returns the flagged
  items, false claims and usage.
- `mark_unverified(answer, items, false_claims, language) -> str` - inserts the
  markers.

It is called in the agent layer, so evals see exactly what users see:

- at the end of `ChatAgent.chat_batch`, after `final_response_text`;
- in the stream path, on the `final` event (`ChatAgent.stream_chat_events` in `agent.py`).

Autonomous agents run through `ChatAgent` and get it too. The save path
(`save_message_to_db`) is deliberately not the hook: evals call `chat_batch`
directly and would not see the markers.

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
`done` arrives about 1-3 s later. The client re-renders the bubble from `done.content`
whenever it differs from the streamed text (`doneContentToRender` in
`web/src/core/stream-done.ts`). Before the final review it did that only when no
tokens had streamed, so streamed answers showed markers only after a reload.

## Verifier

- Model: `GROUNDING_CHECK_MODEL`, default `gemini-3.5-flash-lite`, the newest text
  Flash-Lite model the API lists in Oct 2026. Temperature 0, no thinking, built like
  `title.py`. Its price ($0.30 input / $0.03 cached / $2.50 output per 1M tokens)
  goes into the pricing table only, not the user-selectable model list. If Lite
  proves too imprecise, `GROUNDING_CHECK_MODEL=gemini-3.8-flash` switches it without
  a code change.
- Output: `with_structured_output(GroundingVerdict)`, as the memory defrag job does.
  The schema is `unsupported: list[UnverifiedItem]` plus `false_claims: list[str]`.
  Each item has `text` (the specific exactly as written in the answer) and `kind`
  (`shop | place | price | hours | date | figure | other`). A false claim is a
  sentence, copied exactly from the answer, in which the answer says it verified,
  checked or confirmed something the sources do not support.
- Known facts: the verifier also gets today's date and the user's message, marked as
  always supported. Without them it flagged today's date (given to the model in the
  system prompt) under a fully sourced answer.
- Prompt (precision first):
  - List every concrete, checkable specific in the answer that neither the sources
    nor the known facts contain, or that the sources contradict: names of shops,
    places, venues, products and people, and prices, opening hours, dates and
    figures. Go through the answer line by line, tables included.
  - Never flag general knowledge, advice, the answer's own reasoning, or items the
    answer already labels as unverified or estimated.
  - When unsure, do not flag.
- Items and false claims are kept only if they appear literally in the answer
  (case-insensitive). Items longer than `GROUNDING_CHECK_MAX_ITEM_CHARS` (80) are
  dropped; only false claims may be sentences. At most `GROUNDING_CHECK_MAX_ITEMS`
  (default 8) items and `GROUNDING_CHECK_MAX_FALSE_CLAIMS` (default 3) false claims
  are kept.
- Hard timeout `GROUNDING_CHECK_TIMEOUT_SECONDS` (default 10, the Gemini API minimum deadline).
- Usage (input, output and cached tokens, priced at the verifier model's rates) is
  added to the turn's `usage_info`, so `message_costs` stays accurate.

**Failure handling:** fail open. On a timeout, API error or schema error the check
logs a warning and returns the answer unchanged.

**Telemetry:** one log line per check with `flagged_count`, `false_claim_count`,
`kinds`, `source_chars` and `duration_ms`. Prod logs then show the share of web turns flagged and what gets
caught.

## The markers

Each flagged item gets a marker right after it, at every occurrence, in the answer's
language (`detect_response_language`): `_(neověřeno)_` for Czech, `_(unverified)_`
for every other language.

- If the item is wrapped in emphasis (`**VeloRama**`, `*VeloRama*`), the marker goes
  after the closing asterisks: `**VeloRama** _(neověřeno)_`.
- Overlaps are resolved in one regex pass with the items sorted longest first, so
  "VeloRama.cz" and "VeloRama" never double-mark.
- Protected spans are never touched: markdown link targets `](...)`, inline code,
  and fenced code blocks. A URL is never edited.
- Table cells get the marker inside the cell, so the table still renders.

Each false claim gets the same marker at the end of the sentence.

There is no end note. The marked text becomes part of the saved message content:
later turns see the markers in history, search and copy include them, and a reload
shows the same text. Item kinds are logged only and never shown.

## Configuration

New entries in `src/config.py`, `.env.example` and the docs:

- `GROUNDING_CHECK_ENABLED` (default true) - kill switch.
- `GROUNDING_CHECK_MODEL` (default `gemini-3.5-flash-lite`).
- `GROUNDING_CHECK_MAX_SOURCE_CHARS` (default 60000).
- `GROUNDING_CHECK_MAX_ITEMS` (default 8).
- `GROUNDING_CHECK_MAX_FALSE_CLAIMS` (default 3).
- `GROUNDING_CHECK_MAX_ITEM_CHARS` (default 80).
- `GROUNDING_CHECK_TIMEOUT_SECONDS` (default 10, the Gemini API minimum deadline).

## Testing

- Unit tests (`tests/unit/test_grounding_check.py`, fake LLM):
  - trigger rules: web tool present, empty answer, stopped turn, non-web tools only;
  - source collection and the char cap (most recent kept);
  - known facts (today's date, the latest user message);
  - false claims and the item length cap;
  - marking: emphasis, link targets and code untouched, table cells, overlapping
    items, every occurrence, false-claim sentences, cs and en markers, no items
    leaves the answer unchanged;
  - fail-open on timeout, exception and bad schema;
  - verifier usage added to `usage_info`.
- Hook tests: `chat_batch` and the stream `final` event carry the markers when the
  verifier flags items and leave the answer untouched when it does not. The existing
  `chat_batch` / `stream_chat_events` mock shapes stay the same.
- Evals, before and after:
  - `skill_product_where_to_buy` over 5 runs;
  - the new `cz_grounded_no_note` precision case;
  - a spot-check of `cz_local_lookup`, `web_lookup_cited` and the trip cases for
    spurious markers;
  - the full suite.

  Report the eval cost and the verifier's per-turn cost.

## Rollout

Ship only if the eval gate passes; otherwise nothing goes to production and the
results are reported. After a deploy, watch the telemetry for a week, then decide
whether the default model, the source cap or the prompt needs tuning.

## Revision (Oct 2 2026): why the end note was replaced

The first version appended one note line listing the unverified items. It missed
the gate in every configuration:

| Verifier | `skill_product_where_to_buy` | `cz_grounded_no_note` |
|---|---|---|
| Lite, cap 5 | 0/5 | 5/5 |
| Lite, cap 10 | 1/5 | 1/5 |
| 3.8-flash, cap 10 | 0/5 | 0/5 |
| Lite, cap 8, known facts, recall prompt | 1/5 | 5/5 |

The first rounds were also invalid until the timeout was fixed: the API rejects
deadlines under 10 s, so every check failed open.

With known facts and the recall prompt, the verifier found the right items with good
precision. What failed was the presentation. The judge read the unverified shops and
prices in the main text and tables as stated facts, which an end note does not
change, and the answer's own "Verified: ..." sentences contradicted the note. Hence
the in-place markers and the false-claims list.
