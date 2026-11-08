# Background memory review - design

Status: draft, Nov 8 2026. TODO.md item "Background memory review" (from the
Hermes review, Oct 26 2026).

## Why

The agent saves a memory only when it decides to call `manage_memory` mid-turn.
That misses facts the user mentions in passing ("Ema starts ballet on Tuesdays")
while the turn is about something else. Hermes runs a periodic learning pass
after the reply. We copy it, conservatively: a missed fact costs little, while a
wrong or noisy memory gets injected into every later prompt and erodes trust.

## Goals

- Every few user turns, a cheap model rereads the recent conversation and may add
  memories or patch existing ones.
- **Conservative eagerness (decided by the user):** save only facts likely to
  matter again: people and relationships, places, schedules and routines, stable
  preferences, decisions made. Don't save moods, passing interests or one-off
  context. "When in doubt, don't."
- Writes go straight in through the existing `manage_memory` guards (size caps,
  injection screen, category check, the 200-entry bank). There is no approval
  queue (decided Oct 26 2026).
- A quiet note under the reply that triggered the pass, e.g. "Memory updated:
  Ema - ballet on Tuesdays". Tapping it opens Memories (the Data page).
- **Re-measure (decided by the user):** every write the pass makes is logged so
  we can judge its quality about two weeks after the ship date. A TODO item
  carries the date.

## Non-goals and anti-goals

- No approval queue and no review inbox.
- No pass over agent runs (unattended).
- No pass in anonymous or planning chats.
- No deletes. The pass adds and patches only; removing memories stays with the
  user and the in-turn tool.
- Anti-goal: hardening negative claims. A memory like "the Garmin tool doesn't
  work" turns into refusals later. The do-not-capture list below exists to
  prevent this.
- Anti-goal: duplicates. A fact the bank already holds gets patched or skipped,
  never added a second time.

## Behavior

### When it runs

- **State:** per conversation, in `kv_store`: a turn counter plus a review
  cursor (the id of the last message the pass reviewed).
- **Counting:** the counter goes up by one on each completed user turn, batch
  and streaming alike.
- **Trigger:** at `MEMORY_REVIEW_EVERY_TURNS` (default 6), the pass runs after
  the reply is saved. It reviews every message after the cursor, then moves the
  cursor and resets the counter.
- **Postponed, not skipped:** a turn that called `manage_memory` resets the
  counter, since the agent just curated memory itself, but leaves the cursor
  alone. Earlier passing mentions are still reviewed by the next pass.
- **Window cap:** at most `MEMORY_REVIEW_MAX_TURNS` user turns (default 12)
  after the cursor are reviewed. Older ones past the cap are skipped and logged.
- **No compaction hook (my call):** the TODO proposed a second pass at the
  compaction point. The cursor makes it unnecessary.
  - With the default 12 kept messages, the periodic pass has normally reviewed a
    turn before compaction folds it, and the cursor guarantees nothing between
    passes is skipped.
  - Compaction is also non-destructive: folded turns stay searchable.
  - A compaction hook would mostly reread reviewed turns, and it would hang the
    note on a turn unrelated to the fact.
- **Where:** all non-anonymous, non-planning chats, standing chats included.
  Never agent runs.
- **Kill switch:** `MEMORY_REVIEW_ENABLED` (default true).

### The pass

- **Thread:** a daemon thread, off the request path. A failure only logs; it
  never touches the turn.
- **Model:** the cheap Flash tier (same family as other background
  summarizers).
- **Input:**
  - the messages after the cursor (within the window cap), with tool output stripped;
  - the user's current memory list (ids, categories, text), so the model can patch instead of duplicating;
  - memories the user deleted within `MEMORY_SOFT_DELETE_RETENTION_DAYS`, marked "the user removed these - do not re-add" (my call: re-adding what the user just deleted is the trust failure this design exists to avoid).
- **Output:** a JSON list of `manage_memory` operations, add or patch only, at most `MEMORY_REVIEW_MAX_OPS` (default 3). An empty list is the expected common case.
- **Writes:**
  - Run through the same batch planner as the tool (`_plan_batch`/`_run_batch` in `src/agent/tools/memory.py`), so every guard applies unchanged.
  - Delete operations are dropped before planning.
  - Writes carry the conversation id, as in-turn writes do.
  - **Rejections (my call):** the tool's batch is all-or-nothing and the pass has no retry loop. So the pass applies its ops one at a time: a rejected op is logged and dropped, and the rest still apply. There is no retry and no user-facing error.
  - **Full bank:** when the bank is at its cap, adds are rejected like any other op; patches still apply. The pass can't merge memories, since it never deletes.
- **Prompt rules (the do-not-capture list, copied from Hermes):**
  - transient errors and outages;
  - one-off tasks and requests ("book a table tonight");
  - unresolved attempts;
  - negative claims about tools or capabilities;
  - anything the user asked not to remember;
  - facts already in the list (patch them if they changed, else skip);
  - guesses about the user. Save only what was said, not what was inferred.
- **Untrusted content:** text that came from web pages or files is not a source of memories. The input strips tool outputs, and the existing injection screen still runs on every write.

### The note

- **Where it lives:** the triggering assistant message gets a short label naming
  what was saved or patched, at most two items plus "and N more".
- **How it arrives:** the pass finishes after the reply is on screen, so the
  label reaches an already-rendered message. Updating that message row already
  bumps the cross-device change log. The open chat's in-place merge patches the
  label into the rendered message instead of treating it as an edit; today a
  changed `content` forces a full re-render, and the label must not.
- **Tap target:** Memories (the Data page).
- **Style:** quiet, the same visual weight as the delivery label on scheduled
  turns.
- **No-op passes** show nothing.

### Re-measure

- **Logging:** each applied write logs one line with the user id, conversation
  id, operation, memory id and a truncated excerpt. Logs follow the existing
  rules: user ids, never emails.
- **TODO entry:** about two weeks after ship, count the pass's writes per user
  and sample them for keep or noise. Also check what share of those memories the
  user later deleted or edited. If noise is above roughly 1 in 5, tighten the
  prompt or lengthen the interval.

### Evals

New cases in `evals/`. Each seeds a history and a memory bank, calls the review
pass directly and synchronously (a new case shape), and grades the operations
it returns (my call: the harness runs single turns, and driving six real turns
per case would cost six times as much):

1. **Saves a passing household fact.** A chat about dinner plans mentions "Ema
   has ballet every Tuesday at 17:00", and the pass adds it.
2. **Ignores one-offs and negative tool claims.** A chat with "book me a table
   tonight" and "the weather tool is broken today" produces no write.
3. **Patches instead of duplicating.** The bank holds "Ema - ballet on Mondays"
   and the chat says it moved to Tuesday. The pass patches that memory and adds
   nothing.

## Cost

Flash, roughly one pass per six turns, with a few thousand tokens of input. That
comes to about $1-2/month at current volume, recorded through the usual cost
tracking. Report it in the next product review.

## Left to the builder

- Module layout: the TODO suggests `agent/background_review.py`.
- How the turn-end hook reaches the counter, for both modes.
- Where the label is stored (a column versus a JSON field) and the response schema.
- The exact prompt wording within the rules above.
- Label storage. The open chat's merge (`web/src/core/remote-merge.ts`) compares only `content` and renders only message ids it hasn't seen. A label stored outside `content` therefore needs the merge extended to patch it in place on every device. Don't put it in `content`: that would force the full re-render.
