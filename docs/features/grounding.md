# Grounding Check

Post-answer check of web-tool answers: which specific claims the pages the
turn read support, shown as underlines, source numbers and a footer under the
answer. The prompt-side [grounding directive](agent-tools.md#tool-security)
that came first is in Agent Tools.

Because prompt rules did not work, a check runs after the answer, outside the
model ([grounding_check.py](../../src/agent/grounding_check.py)). It never
edits the answer: it judges specific claims against the pages the turn read
and stores the verdicts as annotations beside the unchanged text. Design:
[annotations spec](../superpowers/specs/2026-10-03-grounding-annotations-design.md)
(superseding the Oct 2 [in-place marker spec](../superpowers/specs/2026-10-02-grounding-check-design.md)).

- **Trigger**: `ChatAgent` calls `grounding_check.apply_grounding()` at the end
  of `chat_batch` and on the `final` event of `stream_chat_events`
  ([agent.py](../../src/agent/agent.py)), so evals see what users see.
  `should_check()` gates it: the check is enabled, the answer is non-empty, the
  turn was not stopped, it is not a `delegate_task` subagent run, and the turn
  has web pages (`turn_pages`) or other web tool text (`uncited_web_text`).
  When it passes, the stream yields `grounding_started` before the verifier
  runs (the footer shows "checking"). Every other turn skips it at zero cost.
- **Numbered pages**: [source_pages.py](../../src/agent/source_pages.py)
  `turn_pages()` is the one list behind both the sources popup
  (`extract_read_sources()` in [content.py](../../src/agent/content.py)) and
  the verifier, so claim source `[2]` is popup entry 2: pages the turn read
  (research pages with content, successful `fetch_url`, `browser` pages,
  `delegate_task` sources; at most 10), else the top 5 search results
  rank-interleaved. `uncited_web_text()` is web text the verifier may use but
  cannot cite (search snippets when pages were read, unparsed web output).
  `format_sources()` gives each page a fair share of
  `GROUNDING_CHECK_MAX_SOURCE_CHARS`.
- **Verifier**: one structured call (`GroundingVerdict`, temperature 0) to
  `GROUNDING_CHECK_MODEL`, prompt in
  [grounding.py](../../src/agent/prompt_texts/grounding.py). Inputs: the
  numbered sources, the answer, and known facts (`known_facts()`: today's
  date, the user's message, this turn's non-web tool results such as calendar
  or Garmin) that always count as supported. Output is two lists of
  `ClaimVerdict` (`quote`, `verdict`, `source`, `source_quote`, `reason`):
  `unsupported` first (every partial, contradicted or not_found claim), then
  `supported` (only businesses, products, prices, hours, event dates, contacts).
  Scope is practical, current specifics - businesses and products, prices,
  stock, hours, contacts, dates of upcoming or scheduled events. History and
  background (past events, biographies, geology, trivia) are never checked:
  "zajímavosti o Radobýlu" (Oct 3 2026) got 5 of 6 historical sentences
  underlined, accurate to its three pages but not what the check is for
  (`cz_history_no_flags`). The prompt gates on "could the reader visit, buy,
  book or contact it now": on captured history answers that cut unsourced
  marks from 18 to 2 in 12 runs, with price recall 86% vs 91% before.
  Verdicts: `supported`, `partial`, `not_found`, `contradicted`. The order
  matters: with one mixed list Lite's recall on unsourced prices was 71%,
  with problems first 89% (Oct 2026 A/B on captured eval answers), and the
  problems stay inside the claim cap. A sentence claiming it verified
  something is a claim too. It must never list the answer's own plan or
  schedule (times, durations) or well-known places (towns, hills, regions).
- **Validation**: nothing the verifier returns is trusted
  ([grounding_annotations.py](../../src/agent/grounding_annotations.py)
  `validate_claims()`). A claim is kept only if its `quote` is literally in the
  answer (case-insensitive) and at most `GROUNDING_CHECK_MAX_QUOTE_CHARS`;
  duplicates are dropped and at most `GROUNDING_CHECK_MAX_CLAIMS` are kept. A
  `source_quote` must be literally (whitespace- and case-normalised) in the
  cited page, or the claim is downgraded to `not_found` and loses its source;
  a supported claim with no number at all is backed by uncited text and stays
  supported. Reasons and passages are clipped to
  `GROUNDING_CHECK_MAX_REASON_CHARS` / `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS`.
  If 3+ unsupported claims are bare times or time ranges they are the
  answer's own timeline and are dropped. Each annotation carries a `prefix`
  (the 32 answer characters before the quote) so the client can anchor the
  right occurrence. Annotations are in answer order.
- **Storage and API**: `apply_grounding()` puts `{"annotations", "summary"}`
  into `usage_info["grounding"]` (summary: `{"checked": true,
  "source_count": N}`), which `save_message_to_db`
  ([chat_save.py](../../src/api/helpers/chat_save.py)) writes to
  `messages.annotations` / `messages.grounding`
  ([0057](../../migrations/0057_add_message_annotations.py)). Batch responses,
  the stream `done` event, and loaded messages carry `annotations` and
  `grounding` (see [Chat and Streaming](chat-and-streaming.md)).
  [0058](../../migrations/0058_convert_grounding_markers.py) converted the old
  inline `_(neověřeno)_` / `_(unverified)_` markers into `not_found`
  annotations with `{"checked": true, "legacy": true}` (no reason or source),
  updating `search_index` too.
- **Deep research**: a [deep research](deep-research.md) report is checked
  by `check_grounding_pages()` against the run's merged pages with
  `DEEP_RESEARCH_GROUNDING_MAX_SOURCE_CHARS` / `DEEP_RESEARCH_GROUNDING_MAX_CLAIMS`
  (`validate_claims(max_claims=...)`); `check_grounding()` wraps the same
  function for chat turns.
- **Later turns**: `format_grounding_context()` adds a `grounding` key to that
  message's `MSG_CONTEXT` ("unsourced: X (reason); contradicted: ..."), capped
  at `GROUNDING_CONTEXT_MAX_CHARS`, so a follow-up does not restate those
  claims as fact. The history text itself is clean.
- **UI**: [annotations.ts](../../web/src/components/messages/annotations.ts)
  anchors each quote in the rendered markdown (markdown punctuation dropped,
  whitespace collapsed, matched with its prefix; code and KaTeX skipped).
  Unsupported claims get a dotted underline (`.claim.claim--<verdict>`);
  supported claims with a source get a superscript source number
  (`.claim-cite`). [grounding.ts](../../web/src/components/messages/grounding.ts)
  `decorateGrounding()` runs on streamed (done), batch and loaded messages and
  adds a footer under the answer text ("N of M claims from sources · 2 without
  a source"; legacy messages show only the problem counts); `showGroundingChecking()`
  shows the "checking" state on `grounding_started`. UI text is English whatever
  the answer's language
  ([grounding-strings.ts](../../web/src/components/messages/grounding-strings.ts)).
  [ClaimCard.ts](../../web/src/components/ClaimCard.ts) opens on hover
  (after `CLAIM_CARD_HOVER_DELAY_MS`) or tap: verdict, reason, the source
  passage, and "Look it up", which sends "Look up and verify: <quote>" as a
  `verify_claim` action (`source_message_id`, `claim_index`, `quote`) via
  `sendUiMessage()` ([messaging.ts](../../web/src/core/messaging.ts); the
  draft is untouched, and while a reply streams it toasts "wait" instead). The
  message renders as an action row ("Looking up “...” · from the answer above
  ↑"), and once its reply exists the card shows "Looked up below ↓", jumping to
  it - see [Action messages](deep-research.md#action-messages).
  Clicking the footer (when there are problems) opens
  [ClaimsSheet.ts](../../web/src/components/ClaimsSheet.ts): a bottom sheet
  below 768px, a popover above, rows ordered contradicted, not_found, partial,
  supported; a row scrolls to the claim and flashes it for `CLAIM_FLASH_MS`.
  Sources stay in the numbered sources popup. Styles in
  [grounding.css](../../web/src/styles/components/grounding.css) with tokens in
  `variables.css`; both components are initialised in `core/init.ts`.
- **Cost**: about $0.004 per web turn. Verifier usage goes into
  `usage_info["grounding_usage"]` and is priced at the verifier's rates by
  `calculate_grounding_cost()` ([utils.py](../../src/api/utils.py)) into
  `message_costs`.
- **Fail-open**: on timeout, API or schema error it logs "Grounding check
  failed" and the message is saved without annotations.
- **Telemetry**: one "Grounding check" log line per check with
  `verdict_counts`, `source_count`, `source_chars`, `duration_ms`, `parsed`.

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `GROUNDING_CHECK_ENABLED` | `true` | Kill switch |
| `GROUNDING_CHECK_MODEL` | `gemini-3.5-flash-lite` | Verifier model (priced only, not user-selectable) |
| `GROUNDING_CHECK_MAX_SOURCE_CHARS` | `60000` | Source text cap, shared across pages |
| `GROUNDING_CHECK_MAX_CLAIMS` | `20` | Max annotations per answer |
| `GROUNDING_CHECK_MAX_QUOTE_CHARS` | `60` | Longer quotes are dropped (claims are short phrases; 120 let whole sentences through) |
| `GROUNDING_CHECK_MAX_REASON_CHARS` | `160` | Reason clip |
| `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS` | `240` | Source passage clip |
| `GROUNDING_CONTEXT_MAX_CHARS` | `400` | `MSG_CONTEXT` `grounding` entry cap |
| `GROUNDING_CHECK_TIMEOUT_SECONDS` | `10` | Floored at `GEMINI_MIN_REQUEST_DEADLINE_SECONDS` (10) |

Client constants in [config.ts](../../web/src/config.ts):
`CLAIM_CARD_HOVER_DELAY_MS` (250), `CLAIM_FLASH_MS` (1600).

Pitfalls learned:
- An end-of-answer note or list of flagged items does not work: readers, and
  the eval judge, take the main text and tables as fact, and the answer's own
  "Verified: ..." sentences contradict the note. Hence verdicts anchored on the
  claim itself in the UI, and in place for the eval judge
  (`annotate_for_judge()` in [run.py](../../evals/run.py)).
- The Gemini API rejects deadlines under 10 s, so a shorter timeout made every
  check fail open (silently, apart from the warning).
- Without known facts the verifier flagged today's date (which the model gets
  from the system prompt) under a fully sourced answer.
- The verifier's passages are not trusted: a passage not found in the cited
  page downgrades the claim to `not_found` rather than showing a source it
  lacks.

Tests: [test_grounding_check.py](../../tests/unit/test_grounding_check.py),
[test_grounding_annotations.py](../../tests/unit/test_grounding_annotations.py),
[test_source_pages.py](../../tests/unit/test_source_pages.py),
[test_grounding_hooks.py](../../tests/unit/test_grounding_hooks.py),
[test_grounding_cost.py](../../tests/unit/test_grounding_cost.py),
[test_message_annotations_storage.py](../../tests/unit/test_message_annotations_storage.py),
[test_migration_grounding_markers.py](../../tests/unit/test_migration_grounding_markers.py),
[test_chat_annotations.py](../../tests/integration/test_chat_annotations.py),
[grounding-annotations.spec.ts](../../web/tests/e2e/grounding-annotations.spec.ts),
[grounding.visual.ts](../../web/tests/visual/grounding.visual.ts).
