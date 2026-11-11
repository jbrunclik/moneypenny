# Program self-tuning: the coach keeps its own setup up to date

Date: 2026-11-11. Status: approved in conversation (Jiri), builder check pending.

## Intent

A program chat (the sports coach, the language tutor) works from a setup the
user rarely touches by hand: its **quick actions** (emoji, label, prompt
body, fields; `program["quick_actions"]` in the programs KV list) and its
**standing instructions** (the program's KV keys: sports `goals`,
`preferences`, `routine`, `progress`; language the equivalents). Jiri never
edited a quick action ("too lazy"); when the coach's instructions were wrong
he asked it in chat to update its KV. The goal: the coach notices what should
change and proposes it, and the user's only job is yes or no.

## Goals

1. **In the moment.** During an ordinary reply, when the coach sees evidence
   (the user typed a request it has seen before; the user corrected it), it
   proposes a change on a proposal card under that reply. Frequent is fine.
2. **On demand.** A **Review** button in the Quick actions sheet asks the
   coach to look over its goals and instructions, the current quick actions
   and the chat's recent turns, and returns a list of suggestions - edit,
   add, remove a quick action; change an instruction - each accepted or
   rejected on its own.
3. **Relevance over frequency** (Jiri: "I don't mind often suggestions, but
   I'd hate irrelevant ones"):
   - every suggestion names its evidence: the specific turns (dates and a
     short quote or paraphrase) it rests on; no evidence, no suggestion;
   - "nothing to change" is a valid outcome of a review;
   - a declined suggestion is not offered again unless new turns back it.

## Non-goals

- Other chats or standing agents (Command Center agents keep their own
  editing flow, `edit_standing_chat`).
- Any change without the user's yes - except what the user asks for in their
  own words, which keeps working directly as today (the coach's `kv_store`
  writes during a conversation are unchanged).
- Rewriting the coach's system prompt (prompt_texts/*) - only per-program
  data.

## Anti-goals

- Generic suggestions ("you might like a 'Plan my week' action") with no
  turn behind them.
- Re-offering what the user declined.
- A card on most replies used as a nudge (see the no-suggestion-chips rule:
  suggestions are changes to the setup, never conversation prompts).

## The decided parts

- **One proposal mechanism.** In-the-moment suggestions are a new proposal
  kind on the existing card (docs/features/proposals.md; `register_kind`):
  the card shows the change as before/after and its evidence; Approve or a
  typed yes applies it, Decline records the decline. The Review list uses
  the same apply code per item.
- **Scope of a change:** quick action add / edit (any of emoji, label, body,
  fields) / remove / reorder is out of scope for v1 unless trivially
  supported; standing instruction change = a merge into one of the program's
  KV keys (a field set, changed or removed), shown as before/after.
- **Review input:** the program's KV data, its quick actions, the declined
  list, and the program chat's recent turns (about the last 40 messages;
  builder's call on the exact window and on trimming tool output).
- **Declined list:** kept per program (in its KV namespace), each entry the
  suggestion's target + a short fingerprint + the date; the review and the
  in-the-moment tool both see it. A suggestion matching a declined entry is
  dropped unless the coach cites turns newer than the decline.
- **User-requested edits stay direct.** Only coach-initiated changes go
  through a card.

## Builder-check calls (Claude's, Nov 11 2026 - check these)

- **Review suggestions live in the sheet, not the chat.** A Review files no
  proposal rows and posts nothing into the program chat: the sheet shows
  the list and calls the shared apply function per accepted item. The coach
  sees applied changes on its next turn through its stored data. Review
  outcomes are logged (one line per item: accepted / rejected) for the A8
  counts, alongside the `proposals` rows of the in-the-moment cards.
- **Which coach writes need a card:** only coach-initiated changes to the
  setup - a quick action, or an instruction key below - that the user did not
  ask for. The documented logging flows stay direct and unchanged: progress
  after a workout, `last_session`, mirroring Garmin targets into `routine`
  after a workout edit the user asked for, vocabulary/SRS updates.
- **"Standing instructions" keys** (the whitelist the tool and the Review may
  propose changes to): sports `goals`, `preferences`, `routine`; language
  `profile`, `grammar`. Not `progress`, `last_session`, `assessment`,
  `vocabulary`, `weak_points`, `session_history`, `stats` - logged data, and
  proposing edits to it would be the irrelevant suggestions to avoid.

## Ignored cards (Jiri's call, Nov 11 2026)

An in-the-moment card that expires because the user carried on chatting is
**not a decline**: the coach may offer it again, but at most once more and
not before a few days have passed (builder's call on the exact gap, ~3 days).
Only Decline, a typed no, or Reject in the Review list put a suggestion on
the declined list.

## Left to the builder

- Model choice and prompt for the review (one structured-output call is the
  expected shape), the size of the turn window, the exact evidence format.
- How the in-the-moment path reaches the model: a tool the coach calls
  (likely) - with its description and the result-side guidance (rule: put
  directives in tool results, not the system prompt).
- UI of the Review list inside the Quick actions sheet (loading state,
  per-item accept/reject, "nothing to change"), following the sheet's
  idiom; desktop and mobile.
- Instrumentation (A8): suggestions made / accepted / declined per kind and
  source (review vs in-the-moment), review cost; a regular-review check and
  a dated re-measure in TODO.
- What's new post (A7): users see the button and the cards.
