# Grounding Annotations - Design

Status: approved design, Oct 3 2026. Supersedes the in-place markers of
[2026-10-02-grounding-check-design.md](2026-10-02-grounding-check-design.md); the
verifier trigger, fail-open behaviour and cost recording stay as designed there.

## Problem

The grounding check (Oct 2 2026) writes `_(neověřeno)_` / `_(unverified)_` into the
answer text after each specific its sources don't support, and the client renders
them as amber pills. A day in prod showed three problems:

1. **Noise, aimed at the wrong unit.** 8 of 10 checked web turns got markers, 4 of
   them 5-8. Turn `47517527` (vehicle registration agencies) read three pages, all
   about one agency, and wrote a second agency from memory: six pills on that
   section's numbers, none on the invented agency itself.
2. **The markers are text.** They are persisted in `messages.content`, so changing
   their wording or look means rewriting stored messages; they carry no reason,
   kind or source; they leak into model history (the model copies them back - see
   `_ALREADY_MARKED`), search, TTS and Copy; the client finds them by regex.
3. **The UI interrupts reading** - a word-sized pill in the middle of sentences.

## Goal and success criteria

The verifier judges every specific claim against numbered sources. The result is
stored as structured annotations next to clean message text and rendered as quiet
underlines, source numbers, cards, a footer summary and a claims list.

- No grounding text in `messages.content`, model history, search, TTS or Copy.
- A new annotation kind needs neither a schema migration nor a rewrite of stored
  messages.
- Turn `47517527`'s shape (a section written from memory) yields one claim-level
  annotation per unsourced claim, including the business name, instead of one per
  number.
- Evals: `skill_product_where_to_buy` stays at least 4/5, `cz_grounded_no_note`
  passes, the full suite pass rate is unchanged.
- Verifier latency p90 stays at or under 2.5 s (prod p90 today: about 1.3 s).
- Every message marked since Oct 2 2026 (7 in prod) is converted.

## Non-goals

- Confidence percentages: the Lite verifier's numbers aren't calibrated; the four
  verdicts carry the useful distinction.
- An "outdated source" kind: page dates aren't extracted. The format leaves room
  for it.
- Rewriting the answer automatically. "Dohledat" (below) covers the fix path with a
  visible, ordinary turn.
- Turns without web tools (unchanged from the Oct 2 design).

## Data model

Two new nullable JSON columns on `messages`:

```json
// annotations: list, in answer order
{
  "type": "claim",
  "verdict": "supported" | "partial" | "not_found" | "contradicted",
  "quote": "Rychlost: 24–48 hodin",      // literal substring of content
  "prefix": "…up to 32 chars before…",   // disambiguates repeated quotes
  "reason": "Stránky popisují jen SPZ Služby…",  // absent for supported
  "source": 1,                            // 1-based index into messages.sources
  "source_quote": "…literal passage…"     // supported / partial / contradicted
}

// grounding: summary for the footer
{"checked": true, "source_count": 3}            // new messages
{"checked": true, "legacy": true}               // converted Oct 2-3 markers
```

- `type` is the extension point: future kinds are new values, rendered by the same
  client code.
- `source` indexes the message's existing `sources` list, so the inline numbers and
  the source chips always agree.
- No `grounding` value means no footer (turns without web tools, older messages).
- Pydantic schemas in `src/api/schemas/` define both shapes; the OpenAPI spec and
  `web/src/types/generated-api.ts` are regenerated (`make openapi`, `make types`).

## One numbered source list

Today the source chips (`extract_read_sources` in `src/agent/content.py`) and the
verifier's input (`collect_web_sources` in `src/agent/grounding_check.py`) are built
independently and can't be cross-referenced. A single function returns the turn's
pages as `[{title, url, text}]` with the existing selection rules (read pages,
falling back to rank-interleaved search results; de-duplicated by URL; same caps).
Page text comes from research `sources[].content`, the `fetch_url` tool output, the
browser result, or the search snippet. The chips use title and URL; the verifier
gets the same list as `[1] title (url)\ntext`, each page capped so the total stays
within `GROUNDING_CHECK_MAX_SOURCE_CHARS`.

## Verifier

Same trigger, model (`GROUNDING_CHECK_MODEL`, Lite), single structured call,
timeout and fail-open as the Oct 2 design. The prompt and schema change:

- It lists **every** specific claim about businesses, events, services, prices,
  hours, dates and contacts - supported ones too - each as the shortest phrase that
  states the claim (a business name, or "Cena: kolem 1 200–1 600 Kč"), never a
  whole paragraph. The NEVER list (the answer's own plan, well-known geography,
  general knowledge, user-supplied facts) stays.
- Per claim: `verdict`, `source` (page number), `source_quote` (copied from that
  page), and for non-supported verdicts a one-sentence `reason` in the answer's
  language.
- False "I verified this" sentences become `contradicted` or `not_found` claims on
  that sentence (the separate `false_claims` list goes away).

Server-side validation (deterministic, in `grounding_check.py`):

1. `quote` must appear literally in the answer (as today), else the claim is
   dropped; `prefix` is taken from the answer, not from the model.
2. `source_quote` must appear literally (whitespace-normalised, case-insensitive) in
   page `source`'s text; otherwise the passage and source are dropped and
   `supported` / `partial` / `contradicted` becomes `not_found`. A card never shows
   a passage the turn did not read.
3. Caps: `GROUNDING_CHECK_MAX_CLAIMS` (replaces `GROUNDING_CHECK_MAX_ITEMS`),
   `GROUNDING_CHECK_MAX_REASON_CHARS`, `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS`.
   `_drop_schedule_times` keeps applying to non-supported claims.

The "Grounding check" log line keeps `duration_ms` and `parsed` and reports counts
per verdict.

## Delivery

- **Saved** with the assistant message (`save_message_to_db`), both modes.
- **Streaming:** tokens are the final text (nothing is inserted any more). Right
  before the verifier call the server emits a new `grounding_started` SSE event; it
  joins `_JOURNALED_EVENT_TYPES` so a resumed stream replays it. `done` carries
  `annotations` and `grounding`. The client's "done text differs" re-render no
  longer fires for grounding.
- **Batch:** the response carries both fields; the existing spinner covers the check.
- **Reads:** conversation GET, message pagination and sync return both fields.

## Model history

History content is clean text. `MSG_CONTEXT` gains a `grounding` entry built from
the persisted annotations: the not_found / partial / contradicted quotes with a
short reason, capped like the tool digests and never containing `-->`. Removed:
`src/agent/grounding_markers.py`, `_ALREADY_MARKED`, the marker regex in
`web/src/utils/markdown.ts`, the marker map in `web/src/constants.ts`, the
copy-back in `web/src/core/file-actions.ts`, and the `.grounding-unverified` CSS.

## Client

**Anchoring** (`web/src/components/messages/annotations.ts`). After markdown
renders, walk the text nodes of `.message-content` (skipping code and link
targets), find each `quote` (using `prefix` to pick among repeats) and wrap it in
`<span class="claim" data-claim="i" tabindex="0">`, split per text node so quotes
across `**bold**` work. A quote that isn't found is skipped (it still appears in the
claims list). `supported` claims get `<sup class="claim-cite">n</sup>` after the
quote instead of an underline.

**Look (A1).** Underline: dotted, 1px, offset 4px, amber at about 45% opacity;
`contradicted` uses a soft red. Source numbers: grey, no background. Colours are new
tokens in `variables.css` for both themes.

**Card** (`web/src/components/ClaimCard.ts`). One delegated handler on the message
list. Desktop: hover after a short delay, or click; mobile: tap; Esc or outside tap
closes; the span gets `aria-describedby`. Content by verdict - heading ("Ve
zdrojích není" / "Zdroj uvádí jinak" / "Částečně ve zdrojích", or the domain and
title for a source number), the reason, the `source_quote` with its number and
domain, and a **Dohledat** button. Converted legacy claims show the heading and a
fixed explanation.

**Dohledat** calls `sendMessage` with a templated follow-up in the answer's
language ("Dohledej a ověř: <quote>"). It is an ordinary turn, so its answer is
checked too.

**Footer** (`web/src/components/messages/grounding-footer.ts`), above the source
chips (which gain their numbers): "Ověřuji proti zdrojům…" between
`grounding_started` and `done`; then "6 z 9 tvrzení ze zdrojů · 2 bez zdroje · 1
jinak než zdroj" (parts with zero omitted; legacy: "3 bez zdroje"). Tappable when any
claim is not supported.

**Claims list** (`web/src/components/ClaimsSheet.ts`). Bottom sheet below the 768px
breakpoint, popover above. Header "Porovnáno se 3 stránkami · 6 z 9 podloženo".
Rows ordered contradicted, not_found, partial, supported: verdict label, quote,
one-line reason or domain. Tapping a row closes the sheet, scrolls to the claim and
flashes its highlight.

UI strings follow the answer's language (`messages.language`), Czech and English.

## Migration `0057`

Python, like the existing migrations:

1. Add `messages.annotations` and `messages.grounding` (TEXT, nullable).
2. For each assistant message whose content contains `_(neověřeno)_` or
   `_(unverified)_`: remove each marker (and the space before it); the quote is the
   phrase right before it, back to the nearest boundary (start of line, list
   marker, `**`, `(`, `:`, `,`, `;`, `–`, `—`); annotation `{"type": "claim",
   "verdict": "not_found", "quote", "prefix"}`; `grounding` = `{"checked": true,
   "legacy": true}`.
3. Update the matching `search_index` rows (it has insert and delete triggers only).

Before deploying, the migration runs against a copy of the production database and
all converted messages are reviewed by hand.

## Configuration

`src/config.py`, `.env.example` and `docs/features/` per the env-var convention:

- `GROUNDING_CHECK_MAX_CLAIMS`, default 20 (replaces `GROUNDING_CHECK_MAX_ITEMS`,
  default 8, which only counted unsupported items); `GROUNDING_CHECK_MAX_FALSE_CLAIMS`
  is removed. The production `.env` follows `.env.example`, so the renamed keys are
  updated there in the same deploy.
- `GROUNDING_CHECK_MAX_REASON_CHARS`
- `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS`
- `GROUNDING_CONTEXT_MAX_CHARS` (the `MSG_CONTEXT` entry cap)

Client constants: the hover delay and the highlight flash duration in
`web/src/config.ts`.

## Testing

- **Backend unit:** the shared source list matches chip numbering; verifier output
  validation (literal quote, literal source passage, downgrade to not_found, caps,
  schedule times); `MSG_CONTEXT` grounding entry; migration quote extraction on
  fixtures shaped like the 7 prod messages.
- **Integration:** batch response, `done` event, conversation GET and sync carry
  `annotations` / `grounding`; `grounding_started` is emitted and replayed on resume.
- **Frontend unit:** anchoring (across bold, repeated quotes, inside code, missing
  quote), footer counts and states, copy yields clean text.
- **E2E:** a per-test `/test/set-grounding-result` hook makes the mocked verifier
  return a canned verdict (the live verifier stays disabled in tests). Underline,
  card, Dohledat, footer states, claims list and scroll-to-claim; desktop and a
  390px mobile viewport; streaming and batch.
- **Visual:** baselines for footer, card and sheet; Linux baselines via
  `/regen-baselines`.
- **Evals:** the judge receives the answer plus a list of its annotations. Run the
  grounding cases (`skill_product_where_to_buy`, `skill_trip_roadstop`,
  `cz_grounded_no_note`, `cz_trip_plan_precision`) and report the cost.

## Rollout

One feature branch; migration verified on a copy of the prod database; single
deploy (health-gated). After a week: verdict counts and latency from the "Grounding
check" log line, and how often "Dohledat" follow-ups appear.
