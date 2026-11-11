# Instructions self-tuning: the assistant keeps its own instructions up to date

Date: 2026-11-11. Status: approved in conversation (Jiri); builder check done, answers below.
Follows [program self-tuning](2026-11-11-program-self-tuning-design.md), which
shipped the same idea for the coaches' quick actions and standing instructions.

## Intent

Every user has **custom instructions** (Settings → AI Instructions; one prose
text on `users.custom_instructions`, injected into every chat's system prompt)
and a **memory bank** (`memories`; facts, preferences, context, goals). Both
drift: people correct the assistant's style in chat ("stop using bullet
points", "answer in Czech") and the correction is forgotten next chat, or
lands in memory where it is one of 200 entries rather than a rule. The goal,
as for the coaches: the assistant notices what should change and proposes it;
the user's only job is yes or no. Jiri: "It should suggest to do what's best
for the given instruction - both custom prompt and memory are valid".

## Goals

1. **Longer instructions.** The limit goes from 2000 to **8000** characters
   (API schema, the Settings textarea and its counter).
2. **On demand.** A **Review** button in Settings → AI Instructions reads the
   instructions, the memory bank, the declined list and the user's recent
   turns across their ordinary chats, and returns suggestions, each accepted
   or rejected on its own, shown with the same cards as the Quick actions
   Review (field rows, "Based on" evidence, Applied / Rejected pills,
   collision refresh).
3. **In the moment.** In an ordinary chat, when the user corrects how the
   assistant behaves in a way meant to last, it offers a card under its reply
   to put that in the instructions.
4. **The right home for each item.** A lasting rule about how the assistant
   responds belongs in the instructions; a fact about the user belongs in
   memory. A suggestion may add, change or remove an instruction passage, add,
   change or remove a memory, **move** an item from one to the other, or
   remove a duplicate.
5. **Relevance over frequency** (same rules as the coaches): every new or
   changed rule cites 1-5 dated turns the user really wrote (clean-up cites
   the items, below); no evidence, no suggestion;
   "nothing to change" is a good answer; a declined suggestion is not offered
   again unless newer turns back it; an ignored card is "not now".

## Non-goals

- Program chats and agents (they have their own setup and their own tool);
  anonymous chats (nothing is kept); the planner.
- Changing how facts are written to memory: `manage_memory` keeps writing
  them inline without approval, and the background memory review keeps
  running. Only Review suggestions and in-the-moment cards go through a yes.
- Rewriting the system prompt (`prompt_texts/*`) beyond the memory-routing
  change below.

## Anti-goals

- Generic advice with no turn behind it ("consider adding a tone rule").
- Rewriting the user's whole instructions text: changes are passages, shown
  as before/after; the rest of the text is untouched.
- A card on most replies (no-suggestion-chips rule: suggestions are changes
  to the setup, never conversation prompts).

## The decided parts

- **Instruction changes are passage edits** on the prose text: append a new
  passage, replace an exact passage, or remove one. A replace or remove
  applies only while its old passage is still in the text exactly once - that
  check is the collision snapshot, so edits the user made elsewhere in the
  text never stale a suggestion. A passage that is gone: the card says it no
  longer applies (same 400 path as the coaches).
- **Memory changes** reuse `apply_memory_batch` with `expected` content as the
  snapshot (`MemoryWriteConflictError` = collision). Protected memories are
  never changed or removed by a suggestion. Category is one of the existing
  four.
- **A move is one suggestion, applied all or nothing**: e.g. instruction
  append + memory delete. If either half no longer applies, nothing changes.
- **Collision refresh** as for the coaches: a 409 carrying the suggestion
  rebuilt against the current state, shown in place ready to accept again.
- **Safety:** proposed instruction and memory text passes `find_injection`
  (the instructions reach every system prompt); suggestions whose text trips
  it are dropped. The size limits hold: instructions ≤ 8000 chars after the
  change, a memory ≤ `MEMORY_MAX_ENTRY_CHARS`, the bank ≤ `MEMORY_MAX_ENTRIES`.
- **Declined list per user** (KV, like `setup_declined`), fingerprints plus
  date and summary; both the Review and the tool see it.
- **One proposal kind** for the cards, `custom_instructions`, on the existing
  proposal card; Approve applies, Decline records the decline.

## Jiri's answers to the builder check (Nov 11 2026)

- **Clean-up may cite the items themselves.** A move, a duplicate or a
  memory that contradicts the instructions needs no recent turn: its
  evidence is the items it rests on (e.g. "Memory: prefers short answers"
  and the instruction line it duplicates), shown under "Based on". A new or
  changed rule still needs 1-5 dated turns. A Review returns at most 8
  suggestions, so a first tidy-up of a large bank takes a few rounds.
- **Lasting rules about how to respond go to the instructions, not memory.**
  The memory prompt (`prompt_texts/memory.py`) and the background memory
  review (`src/agent/memory_review.py`) stop saving them as `preference`
  memories: in chat the assistant offers the instructions card instead; the
  background review skips them. Facts about the user stay in memory,
  written silently as today.
- **Instructions stay global**: an accepted rule applies to every chat,
  coaches and agent runs included, as today. Cards and the Review say so
  (the Settings section already reads "Tell the AI how to respond").

## Builder-check calls (Claude's - check these)

- **Memory suggestions are limited to the instructions' border**: moves,
  duplicates, contradictions, and a memory the user corrected in chat. No
  plain "add a fact" suggestions - those stay with `manage_memory` and the
  background review, which would otherwise compete with a decline here.
- **Re-offer and expiry count per user** (instructions are global), not per
  chat as for the coaches.
- **A move spans two tables in one SQLite transaction.**

- **Review input window:** the last ~60 user messages across the user's
  ordinary (not program, agent, planner or anonymous) chats, each with a short
  excerpt of the assistant reply it answered (a correction only makes sense
  next to what it corrects). Dates are local days; evidence must cite a day
  the user wrote on in that window.
- **The in-the-moment tool** (`propose_instruction_change`) is bound only in
  ordinary non-anonymous chats. Its description says when to use it (a
  correction of behaviour meant for every chat) and when not (a one-off
  request, a fact about the user - that stays `manage_memory`). Re-offer
  rules mirror `propose_setup_change` (once more, after
  `SETUP_REOFFER_AFTER_DAYS`).
- **Unsaved textarea edits:** pressing Review blurs the textarea, which saves
  it first; an accepted instruction change updates the textarea and the store.
- **The Review UI** reuses the Quick actions Review component, generalized
  over its texts (title, loading steps, empty and failed lines); it renders
  inside the AI Instructions section on desktop and mobile.

## Left to the builder

- Model and prompt for the review (one structured-output call, as for the
  coaches), the exact window, trimming.
- The flat schema the model returns and how it maps to changes.
- Instrumentation (A8): suggestions made / accepted / rejected / declined per
  target (instruction, memory, move) and source (review, card), refusals with
  reason, review cost and duration, the instructions length after a change;
  a check in docs/regular-review.md and a dated re-measure in TODO.
- An eval for the tool: proposes on a lasting style correction, stays quiet
  on a one-off request and on a plain fact (report the cost).
- Docs (memory-and-context.md: Custom Instructions) and a What's new post (A7).
