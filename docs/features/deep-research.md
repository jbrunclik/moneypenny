# Deep Research

The agent offers a deep research run next to its quick answer when a question
needs several options compared or several current facts checked. Accepted,
parallel subagents research the sub-questions while sharing a board, a Pro model
writes a report, and the [grounding check](grounding.md) numbers its claims to
the pages the run read. A report can lead to another round.

Design: [deep research spec](../superpowers/specs/2026-10-03-deep-research-design.md).
Where the code and the spec differ, the code wins; the differences are noted
on these pages.

This page covers what the user sees. The rest of the feature:

- [Deep Research Pipeline](deep-research-pipeline.md) - start, producer, briefs,
  subagents and the shared board, merge, writer, grounding check, follow-ups;
  deadlines, Finish now and Stop; concurrency
- [Deep Research Storage, Events and Actions](deep-research-data.md) -
  `messages.research`, `research_*` SSE events, `messages.action` and action rows
- [Deep Research Cost and Operations](deep-research-ops.md) - cost and the
  estimate, push, configuration, telemetry, evals, pitfalls, tests

## How the user meets it

- **The offer.** The main chat agent calls `propose_deep_research(question,
  context, sub_questions, run_now=false)`
  ([tools/deep_research.py](../../src/agent/tools/deep_research.py), description
  in [prompt_texts/deep_research.py](../../src/agent/prompt_texts/deep_research.py))
  together with a short normal answer. The tool has no side effects: when the
  reply is saved, `extract_offer()` ([offer.py](../../src/agent/deep_research/offer.py))
  reads the last call's arguments off the turn and `build_offer()` validates
  them and stores the offer on that assistant message. An invalid plan stores
  nothing; the tool itself runs `validate_plan()` first and answers "Offer NOT
  recorded: <error> Fix the plan and call propose_deep_research again." so the
  model can retry instead of promising a card that never appears. It is bound for ordinary chats only (including anonymous ones), never
  for planner, sports or language programs or agent conversations, and not
  inside subagents. The [product-research skill](../../src/agent/skills/product-research/SKILL.md)
  step 2 tells the agent to offer it for a real multi-product comparison
  instead of researching a long list itself.
- **The card** ([research-offer.ts](../../web/src/components/messages/research-offer.ts))
  under the answer (after the grounding footer): a soft card with a sparkle
  icon and "Research this in depth?" (or "Research further?" for a follow-up
  offer), the estimate as two quiet tags ("~7 min", "~12 Kč"), the editable
  context line (✎, kept inline after a long context), the sub-questions as
  textareas with ✕, "+ Add a question or topic", **Start** (a filled accent
  button) and **No thanks**. The live progress panel uses the same card
  language (see [Progress UI](#progress-ui)).
  The estimate is recomputed live by `estimateFrom()` from the `rates` stored on
  the offer (the same formula as [estimate.py](../../src/agent/deep_research/estimate.py);
  the spec's config endpoint is not used). Start is disabled outside 1 to
  `DEEP_RESEARCH_MAX_SUB_QUESTIONS` items; the client limits in
  [config.ts](../../web/src/config.ts) mirror the server defaults and the server
  enforces them. The currency label is hardcoded "Kč" (`cost_czk` is in
  `COST_CURRENCY`).
- **Start** ([core/deep-research.ts](../../web/src/core/deep-research.ts)
  `startDeepResearch()`) sends the user message "Start deep research" with
  `deep_research: {offer_message_id, sub_questions, context}` and a
  `deep_research` action, through `sendUiMessage()` (refused with a toast
  while a reply in the conversation is still running). The card collapses to
  "Deep research started" (with "Report below ↓" once the report exists); if
  the send fails the editor comes back.
- **No thanks** calls `PATCH /api/messages/<id>/research-offer` with
  `{"status": "declined"}` (the spec's `/conversations/<c>/messages/<m>/...`
  path became this one); the card disappears. A declined or superseded offer
  renders nothing. Starting and declining are one conditional UPDATE
  (`db.decide_research_offer()`, `_decide()` in
  [plan.py](../../src/agent/deep_research/plan.py)): the new research JSON is
  written only while the offer's status (`$.offer.status` or
  `$.run.followup.status`) is still `offered`, so two devices cannot both
  start it; the loser gets `OfferConflict`.
- **Autostart.** For an explicit request ("prozkoumej to důkladně", "deep
  research") the agent sets `run_now`. The model's `run_now` alone is not
  enough (it was seen setting it on an ordinary question): `extract_offer()`
  stores `autostart: true` only when `asks_for_deep_research()`
  ([offer.py](../../src/agent/deep_research/offer.py)) also finds the request
  in the user's own message (`deep research`, `důkladn`, `hloubkov`,
  `prozkoum`, `in depth`, `thorough`; `chat_save.py` passes the message
  text). The tool's result tells the model the user will see the plan before
  it starts. The card then opens in the editor with a countdown of
  `DEEP_RESEARCH_AUTOSTART_SECONDS` (8, [config.ts](../../web/src/config.ts)):
  "Starting in N s", **Start now** and **Edit plan**; any edit (typing, ✕,
  add, Edit plan) pauses it, and the user starts with Start now. Only for a
  reply that just arrived (stream `done` or batch reply, `live: true`) and
  once per page, never from history or a re-render, so a second device
  opening the chat does not start a second run. The countdown's start waits
  (`whenIdle`) until the offer turn is no longer the conversation's active
  request; a refused send brings the editor back.
- **Rounds.** A finished report carries a follow-up offer (2-4 open questions,
  `kind: "followup"`, round + 1) with the same editor. Its subagents and writer
  get the previous report. No cap on rounds; one open offer per conversation
  (a new offer, or a report with a follow-up, marks older open ones
  `superseded`).
- **Progress and the chip.** See [Progress UI](#progress-ui).

## Progress UI

[research-progress.ts](../../web/src/components/messages/research-progress.ts)
keeps a `ResearchProgress` model on the `StreamingState`
(`applyResearchEvent()`, wired in [research-stream.ts](../../web/src/core/research-stream.ts)
from [stream-events.ts](../../web/src/core/stream-events.ts)), so a
conversation switch that re-creates the bubble loses nothing. The panel at the
top of the streaming bubble is the same soft card as the offer: a sparkle
header ("Researching…", or "Writing the report from N sources…") with the
clock ("2:31 · ~5 min"), a progress bar (share of items finished; full while
writing), the items with a leading status icon (spinner, ✓, ◷ waiting, ✕,
–, ⏱, ○ queued) and the pages each read, every shared finding ("② ...",
already clipped at a word by the server), and **Finish now** ("Finishing…"
once pressed; gone while writing). A one-second tick updates the clock only.
On `done`, `finishResearchMessage()` replaces the panel with the report
summary, a `<details>` pill "Deep research · 5 questions · 34 pages · 6 min"
(plus "· finished early") that shares its pill style with the
[action rows](deep-research-data.md#action-messages). Expanded, it reuses the progress item rows
and lists the shared findings clamped to two lines; a tap on a finding opens
it (`is-open`). It also renders the follow-up offer. Styles in
[research.css](../../web/src/styles/components/research.css).

## See Also

- [Grounding Check](grounding.md) - claim annotations, the claim card
- [Chat and Streaming](chat-and-streaming.md) - stream turn, Stop, resume
- [Agent Tools](agent-tools.md) - `propose_deep_research`, skills
- [Cost Tracking](cost-tracking.md) - message costs
- [Evals](../testing/evals.md) - running and authoring cases
