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
  `delegate_task` sources; one per URL with its longest text, the newest 10),
  else the top 5 search results
  rank-interleaved. `research`'s snippet-only results (failed fetches, then
  `unfetched` candidates) count as search results: the model reads them too,
  and a turn whose fetches mostly failed (403/429) otherwise had its products
  flagged as unsourced. `uncited_web_text()` is web text the verifier may use but
  cannot cite (search snippets when pages were read, unparsed web output, a
  `delegate_task` subagent's answer - which used to sit in KNOWN, exempt
  from the check).
  It also gets the claims **earlier replies** had verified (`earlier_verified()`:
  quote, page title and URL, and the page's quote, from the history's
  `verified_claims` metadata, which the chat model does not see). Before this,
  a follow-up restating a fact sourced two turns earlier was flagged red
  whenever this turn's pages lacked it (Oct 11 2026, a senate-election
  conversation: 3-7 false flags in a replay, 0 after). Only supported claims
  carry over, never an earlier reply's own text, so an unverified claim never
  becomes evidence. The same conversation once got "the source says
  otherwise" for a claim the page merely did not cover ("Kuba's man Tomáš
  Fiala"); a stricter `contradicted` definition in the prompt did not help in
  a replay (new wording 1 false contradiction in 3, old 0 in 3) and was not
  kept - the earlier-turn evidence cleared that claim instead.
  `format_sources()` shares `GROUNDING_CHECK_MAX_SOURCE_CHARS` by
  water-filling: short pages keep all their text and leave the rest to long
  ones (an equal split cut long `fetch_url` pages the model had read). Claims
  earlier replies verified come before the snippets in the unnumbered text.
- **Verifier**: one structured call (`GroundingVerdict`, temperature 0) to
  `GROUNDING_CHECK_MODEL`, prompt in
  [grounding.py](../../src/agent/prompt_texts/grounding.py). Inputs: the
  numbered sources, the answer, and known facts (`known_facts()`: today's
  date, the user's message, the images and PDFs attached to it
  (`user_files()`), this turn's non-web tool results such as calendar or
  Garmin) that always count as supported. Files ride with the prompt as one
  multimodal message (`verifier_files()`), each group under a label: the
  user's are KNOWN; the newest 4 the turn's tools returned (`fetched_files()`:
  fetched PDFs and images, browser screenshots) are unnumbered sources - a
  fetched menu PDF used to reach the verifier as one line of text. "The
  user's message" skips the graph's cached-mode guidance (round nudges and
  retries are `[SYSTEM GUIDANCE]` HumanMessages), which KNOWN used to quote
  in its place, losing the user's text, files and earlier tool results. Output is two lists of
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
  `source_quote` must be in the cited page's title, URL or text, compared as
  plain text (markdown, HTML tags and entities, typographic quotes and dashes,
  case and whitespace folded; "..." may join fragments that appear in order),
  or the claim is downgraded to `not_found` and loses its source - a verbatim
  match failed on 24% of real citations (Oct 2026 replay), 5% after this;
  a supported claim with no number at all is backed by uncited text and stays
  supported. A supported claim the verifier marks `about_present` (who holds a
  role, belongs to a party, leads something now) whose cited page is an
  article published more than `GROUNDING_PRESENT_MAX_AGE_DAYS` before today
  becomes `partial` with `STALE_REASON` ("That article is from ..."). The
  verifier only judges whether a claim is about the present; the date maths is
  the server's, because the Lite model ignored a date rule in its prompt (an
  Oct 2025 article "supported" a politician's old party 6 of 6 times; with the
  split, 8 of 8 replays were partial). Reasons and passages are clipped to
  `GROUNDING_CHECK_MAX_REASON_CHARS` / `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS`.
  If 3+ unsupported claims are bare times or time ranges they are the
  answer's own timeline and are dropped. Each annotation carries a `prefix`
  (the 32 answer characters before the quote) so the client can anchor the
  right occurrence. Annotations are in answer order.
- **Safety net** ([specifics_net.py](../../src/agent/specifics_net.py)): when
  the verifier returned any claim, prices and sites it skipped are added as
  `not_found` - a price whose numbers are neither in the sources nor in KNOWN
  (decimal zeros folded: "6490.0 CZK" is 6 490), and a linked or named site
  whose domain no page read, snippet or KNOWN text names. Not flagged: 0, an
  explicitly unverified one, and an amount right after another number and
  "(" or "=" - the answer's own conversion or split ("43 300 Kč (cca
  1 730 €)"), a third of its price flags in Oct 2026 prod.
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
- **Deep research**: a [deep research](deep-research-pipeline.md) report is checked
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
  it - see [Action messages](deep-research-data.md#action-messages).
  Clicking the footer (when there are problems) opens
  [ClaimsSheet.ts](../../web/src/components/ClaimsSheet.ts): a bottom sheet
  below 768px, a popover above, rows ordered contradicted, not_found, partial,
  supported; a row scrolls to the claim and flashes it for `CLAIM_FLASH_MS`.
  Sources stay in the numbered sources popup. Styles in
  [grounding.css](../../web/src/styles/components/grounding.css) with tokens in
  `variables.css`; both components are initialised in `core/init.ts`. The
  footer lines under an answer (this footer, a deep research offer) keep equal
  ink gaps above and below each rule: body text carries about 7px of trailing
  leading, so `.grounding-footer` has a larger `padding-top` than
  `margin-top` and a fixed 16px `line-height` (measured to ±1px; re-check the
  visual baselines when changing either).
- **Cost**: about $0.004 per web turn. Verifier usage goes into
  `usage_info["grounding_usage"]` and is priced at the verifier's rates by
  `calculate_grounding_cost()` ([costs.py](../../src/utils/costs.py)) into
  `message_costs`.
- **Scope**: practical, current specifics (businesses, prices, hours, upcoming
  dates) and, since Oct 11 2026, RECENT NEWS facts from the last 12 months
  before TODAY (announcements, approvals, who holds a role now) - the prompt is
  formatted with today's date. History and older events stay out of scope.
  See [Current Facts](freshness.md).
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
| `GROUNDING_PRESENT_MAX_AGE_DAYS` | `183` | An article older than this cannot support a present-tense claim (`partial`) |
| `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS` | `240` | Source passage clip |
| `GROUNDING_CONTEXT_MAX_CHARS` | `400` | `MSG_CONTEXT` `grounding` entry cap |
| `GROUNDING_CHECK_TIMEOUT_SECONDS` | `10` | Floored at `GEMINI_MIN_REQUEST_DEADLINE_SECONDS` (10); a deep research report uses `DEEP_RESEARCH_GROUNDING_TIMEOUT_SECONDS` (`check_grounding_pages(timeout_seconds=...)`) |

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
- Without the user's images it flagged seat counts read off a user's poll
  screenshot as "contradicted" by a stale article (Oct 2026); the user's "Look
  it up" on that false flag then set off a turn defending a correct figure.
  Eval `cz_screenshot_poll_grounding`.
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
