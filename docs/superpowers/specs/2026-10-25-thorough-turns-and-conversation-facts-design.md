# Thorough turns and conversation facts

Status: design, approved for planning once reviewed. Date: 2026-10-25.

## Why

Two complaints from daily use, in order of how much they hurt:

1. **Settled facts get lost between turns.** In a long chat the user corrects
   Moneypenny ("all partitions are reinforced concrete except one brick wall",
   "room 2141.5 is X", "that is already installed") and a few turns later she
   proposes things that contradict it. The user ended up hand-writing an
   "unmovable facts" section into a prompt and taking the task to another
   assistant.
2. **She stops too early on work that deserves depth.** A floor-plan task
   (measure from an uploaded PDF, respect the settled facts, draw a plan)
   got one shallow pass. The other assistant spent minutes per turn and got
   it right.

### What the evidence showed (one ~50-message production chat, Oct 25 2026)

- The floor-plan PDF was inline only on its upload turn. Later turns saw its
  name. When the model did call `retrieve_file`, it then tried to read it in
  `execute_code`: the sandbox has no access to conversation files and no PDF
  library, so the step failed. The retrieved file was aged to a stub after one
  round, and the plan was drawn from guesses.
- That turn hit the tool-round cap exactly: soft nudge at round 4, "answer
  now" at round 6 (`AGENT_MAX_TOOL_ROUNDS = 6`).
- `generate_image` ran with `used_reference_images: false` although the user
  asked it to work from the original plan.
- Compaction kicked in at 30 messages. The chat mixed several topics, so the
  user's corrections ended up as single lines in 250-word segments alongside
  unrelated topics.
- When corrected, the model saved the facts to the user's **global** memory.
  Nothing kept them for this conversation.
- Cost was never the constraint: the most expensive turn cost ~$0.21, and
  typical turns cost $0.02–0.05. Flash ran at the API default thinking level.

## Goals

- Facts the user settles in a conversation stay in force for the rest of
  that conversation, however long it gets.
- For a request that deserves it, Moneypenny offers to work through it
  thoroughly; once accepted, that turn has the budget to finish the job
  properly.
- Keeping more of a long conversation verbatim before summarising.

## Non-goals

- Changing the model for thorough turns. The conversation's model is kept;
  depth comes from thinking level and step budget. (User decision.)
- Re-sending attachments automatically on every turn. The agent already has
  `retrieve_file`; it should fetch what is relevant. (User decision.)
- Changing deep research. It keeps its engine (parallel web subagents, Pro
  writer, grounding check); it is for questions about the outside world.
- User editing of the facts list. (User decision: visible, not editable.)
- Backfilling facts for existing conversations. (User decision.)

## Anti-goals (would be a failure even if it works)

- Thorough mode starting without the user's consent, or a single thorough
  turn costing well over the user's ceiling of about **$1**.
- The facts list turning into a second memory store that duplicates global
  memories or fills with chatter. It should read like the hand-written
  "unmovable facts" section: short, decisive, current.
- Ordinary short turns getting slower or noticeably more expensive.
- A sticky "deep mode" that silently keeps spending on later turns.

## Part 1: Conversation facts

A per-conversation list of settled facts and decisions, maintained by the
agent.

- **What goes in:** user corrections, decisions made, constraints, things
  already done ("blackout blinds already installed"), identifiers the
  conversation keeps using, and conclusions the agent worked out in earlier
  turns (measurements, computed values) so they don't shrink to 400-character
  `tool_outputs` snippets. When a fact is superseded, the agent replaces or
  removes it rather than appending a contradiction.
- **How it enters context:** sent verbatim with every turn of that
  conversation, outside compaction, so a summary can never squeeze it. It
  belongs with the per-request dynamic context (the `[CONTEXT]` block), not
  the cached static prefix.
- **How the agent maintains it:** a tool (new or an extension of an existing
  one; builder's call) that adds, replaces and removes entries. The prompt
  must tell the agent when to use it versus `manage_memory`: conversation
  facts are about *this* conversation's subject (the flat, the trip, the
  project); global memory is about the user across conversations. Precedent:
  program conversations already keep a kv_store "notebook" injected per turn
  (`PROGRAM_KV_INJECTION_MAX_CHARS`).
- **How the user sees it:** visible in the conversation, read-only, in the
  same spirit as the compaction chip and popup (header chip with a count, and
  a popup listing the facts). To change a fact the user says so in chat. Must
  work on desktop and mobile.
- **Bounds:** a size cap so it can't grow without limit (builder picks the
  number; it should comfortably hold ~30 short facts). The tool result must
  say when the cap is hit so the agent consolidates.
- **Facts follow the reply that set them** (my call). Each entry records the
  assistant message that last set it. Deleting that message removes the
  entry; regenerating that turn replaces the facts it set with whatever the
  new answer records. A wrong fact can't outlive the answer that introduced
  it. Restoring an earlier value that a deleted turn overwrote is not
  required.
- **No extra round** (my call). Recording facts must not cost an extra
  model round on ordinary turns. One option: handle it like
  `set_conversation_title`, recorded from the turn's tool calls without
  routing back to the model. Note the opposite lesson for `manage_memory`,
  which must stay inline because it reports outcomes; the builder should
  decide which applies here.
- **Rollout** (my call). Behind a config flag. It's switched on once the
  facts-retention eval passes and a latency/cost check shows ordinary turns
  aren't slower or noticeably more expensive.
- **No backfill.** Existing conversations start with an empty list; facts
  accumulate from the next turn onward. (User decision.)
- **Scope:** ordinary chats. Whether planner/sports/language programs and
  agent conversations get it is the builder's call; they already have their
  own notebooks.

## Part 2: Thorough turns

### How it starts

Same consent pattern as deep research, reusing its plumbing:

- The agent answers normally and, when the request deserves more (multi-step
  work on the user's own material, a result that must stay consistent with
  settled facts, a drawing or calculation that needs checking), attaches an
  offer: "Work through this thoroughly?" with a time and cost estimate and a
  short plan.
- **Start** runs the thorough turn; **No thanks** dismisses the card.
- An explicit request in the user's own words ("důkladně", "thoroughly",
  "take your time", …) autostarts after the same short countdown, with the
  same guard deep research uses (the model's flag alone is not enough; the
  user's text must also ask).
- **Per turn.** Accepting covers that one answer. The next turn is ordinary
  and asks again if needed. (User decision.)
- **Regenerating a thorough answer asks again.** A rerun of a thorough turn
  doesn't silently spend again, and doesn't silently drop to ordinary. The
  user is asked whether to redo it thoroughly (with the estimate) or as an
  ordinary answer. (User decision; the UI form is the builder's call.) So the
  "this turn was thorough" marker must live somewhere the rerun path
  (`_resolve_rerun` in `src/api/helpers/chat_turn.py`) can see it.

Implementation direction (my call): generalise the offer to carry a kind:
`research` (today's deep research) or `work` (new). The card, estimate tags,
Start / No thanks, autostart countdown, the conditional "decide" update that
stops two devices starting it twice, and the PATCH decline endpoint are
shared. How the agent proposes it (a new tool or a `kind` argument on the
existing one) is the builder's call. Only one open offer per conversation
already holds and should keep holding across both kinds.

### What a thorough turn does differently

Same model as the conversation. Changes, all scoped to that one turn:

1. **Thinking level high.** A separate effort is evaluating a *low* default
   for ordinary turns; the thorough turn sets its own level regardless of the
   default. `thinking_level` is today per model in `Config.MODELS`; it needs a
   per-turn override.
2. **Bigger budgets, not a bigger round count.** Thorough turns use the
   per-turn budgets from [Turn budgets](#turn-budgets-replace-the-round-cap)
   with larger values (~$1 cost ceiling, a longer wall clock); no separate
   machinery.
3. **Attachments stay readable through the turn.** Multimodal tool results
   the turn retrieved are not aged to stubs while that turn is running
   (ordinary turns keep today's aging).
4. **Check before answering.** Before the final answer, the agent checks its
   draft against the conversation facts and the user's request and fixes
   contradictions. Whether this is a prompt instruction, a guidance message
   injected at the end, or a separate pass is the builder's call; past audits
   found that directives attached to tool results work better than prompt
   text.
The card's estimate needs a formula like deep research's `estimate.py`,
based on rounds × typical round cost at high thinking.

### Turn budgets replace the round cap

Decided Oct 26 2026, after comparing with Hermes Agent, which dropped its turn
cap ("caps caused silent mid-task truncation") and its intermediate budget
warnings ("made models give up early"). Applies to **every** turn; a thorough
turn only raises the values.

The round count stands in for three different risks and measures each badly
(a round's cost grows with history length; one research round takes ~10 s
while six quick lookups are fast; six productive rounds and six identical
failing searches look the same). Give each risk its own guard:

1. **Drop the round-4 "aim to answer within a round or two" nudge**
   (`AGENT_TOOL_ROUNDS_SOFT_NUDGE`); at most keep a batching hint with no
   pressure to finish.
2. **Cost guard** - running turn cost from the usage already recorded per
   turn; stop taking steps near the ceiling (ordinary ~$0.15, thorough ~$1;
   typical turns cost $0.02-0.05).
3. **Wall-clock budget** - one "wrap up now" notice at ~80%, appended to the
   latest tool result (results are read; prompt text is not).
4. **Loop detector** - hash tool name + canonical args; warn, then block, on
   repeated identical failures and A-B-A-B cycles; a successful write resets
   the count; a second byte-identical large result becomes a back-reference
   (Hermes `agent/tool_guardrails.py`).
5. **Round backstop ~20** against runaways only.
6. **At any limit: one final call with tools disabled** that answers from what
   was found and names what is left, instead of repeating "stop calling tools"
   every round. Keep `stopped_early` + Continue. Check first whether Gemini
   `function_calling_config` mode `NONE` works with the explicit context cache
   (the cache holds the tool declarations); if so the final call stays cached.

Risk: the cap exists because the model drip-feeds single calls; the 1.4% of
long-hunt turns (Oct 1-10) may get slower and costlier without better
answers. Measure: eval A/B of both versions (rounds, cost, judge score; include
hard-to-find and the floor-plan case), then after shipping cap hits, cost per
turn and p90 latency from `message_costs`.

## Part 3: Context fixes for every turn

1. **Compact later.** Today: more than 30 messages or ~60k estimated tokens.
   Direction agreed, but the exact sweet spot is to be measured, not guessed.
   Use the existing fact-recall probe (Sep 2026: 55% → 86% with the segmented
   rework) on the user's own long conversations (with consent, since the
   content goes to Gemini), plus per-turn cost at each candidate threshold.
   Candidates up to ~150k tokens. Thresholds stay config values.
2. **Conversation files in the code sandbox.** `execute_code` gets a way to
   use the conversation's uploaded files (for example copying a named
   attachment into `/work`), and the sandbox image gets a PDF library (text,
   vector and image extraction, such as `pymupdf` or `pypdf` plus
   `pdfplumber`). This is what "the agent has the tools to fetch them" needs
   in order to be true for measuring and drawing. (My call; it extends the
   existing tools rather than re-sending attachments.)
3. **Reference images for image generation.** When the user asks to work
   from an uploaded image or plan, `generate_image` should be able to use it
   as a reference. Check whether this is a prompt/tool-description gap or a
   missing capability before changing code.
4. **Earlier findings** survive through the facts list (Part 1), not by
   enlarging `tool_outputs`.

## Constraints

- Production daily driver: every step ships behind config defaults that keep
  ordinary turns unchanged until it is measured.
- The repo is public: no hostnames or infrastructure in docs or commits.
- Batch mode must match streaming for the offer card and the thorough turn.
- New SSE event types (if any) must join the stream journal's journaled set.
- New env vars: `src/config.py` with a default, `.env.example`, and the
  relevant `docs/features/` page.
- Report the cost of any eval or probe runs.

## How we'll know it worked

- Evals: a multi-turn case where the user states facts early, talks about
  something else past the compaction point, then asks for something that
  would contradict them. Pass means no contradiction.
- Evals: offer behaviour. It is offered for a multi-step task on the user's
  material and **not** offered for small talk or quick questions.
- A thorough turn on a floor-plan-like task actually reads the PDF in the
  sandbox and stays under the cost ceiling.
- Production logs after release: thorough-turn cost distribution, offers
  versus accepts, rounds used, facts list sizes.

## Left to the builder

- Tool shape and names for the facts list and the offer kind.
- Storage for facts (kv_store namespace vs table) and the UI component
  details, within the visible, read-only constraint.
- Round cap, cost-guard mechanics, estimate formula.
- Self-check mechanism.
- Order of delivery. A suggested order: facts list → sandbox files and PDF
  library → thorough turns → compaction threshold tuning.
