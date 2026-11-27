# Current Facts (Freshness)

How the agent gets facts that changed after its training data: a gate that
looks things up before the answer, dated search results, snippets that are not
"verification", and a grounding check that covers recent news.

## Why

Oct 2026, two family conversations (a September Apple keynote, the Prague
council a day before the city election), from the production logs:

- 4 of the first 6 turns about the keynote, and about half the election turns,
  ran **no tool at all** and were answered from training data ("GPT-4o is the
  main partner", the 2023 council as current).
- Searches that did run had **no time anchor** ("apple intelligence siri
  architecture"), so they found 2024 pages, presented as this month's news.
- Snippet-only answers were introduced as "Ověřeno přímo z oficiálních zdrojů";
  pages were read twice in ~40 turns.
- On pushback the agent **agreed** ("Máš stoprocentní pravdu") and presented an
  old 2024 footnote as a quote from the slide.
- The grounding check never ran on 26 of 40 replies, and on the rest it judged
  nothing: "past events" were out of its scope.

The prompt already said "ALWAYS use web tools for recent events"; prompt rules
were measured to be ignored (see [Tool Round Economics](../architecture/agent-graph.md#tool-round-economics)).
So every measure below rides on code or on tool results.

## The freshness gate

[freshness.py](../../src/agent/freshness.py), prompt in
[prompt_texts/freshness.py](../../src/agent/prompt_texts/freshness.py).

1. Before a regular chat turn, `ChatAgent` (`chat_batch` and
   `stream_chat_events`) asks `FRESHNESS_GATE_MODEL` with the user's latest
   message, the reply before it (MSG_CONTEXT stripped) and TODAY: does the
   answer need current facts? Yes for recent or upcoming events, who holds a
   role now, current products/prices/rules/schedules, follow-ups about such an
   event, opinions or strategy about a current situation (politics, a company,
   a market - "who should lead it?"), and **whenever the user disputes a fact
   or asks to check it**. No for chit-chat, writing/translating, maths, code,
   timeless knowledge, history, the user's own data. The opinion rule came from
   an Oct 2026 conversation whose rebrand-strategy turn was judged "an opinion"
   and answered from stale memory (Kuba still in ODS, Fiala its face):
   `fresh_opinion_current_politics` went from 0 of 3 lookups to firing every
   time, but the answer can still name people the queries never asked about
   from memory - the case passes about a third of the time and stays a
   baseline target. Such a claim is now flagged when its only support is an old
   article (the grounding age rule) or no page at all.
   The chat routes start the gate as soon as the turn is accepted
   (`build_turn_context` -> `freshness.start_gate`, Nov 16 2026), so it runs
   while the standing context loads, the history is compacted and the prompt
   is built; the agent then waits only for what is left
   (`decide_freshness(messages, pending)`, the cap counted from the start).
   From the route the gate sees the agent's text (with its guidance notes), the
   previous reply and the attachment count (images, PDFs, media) - not the
   text extracted from attached office documents. Not started for the planner
   or a deep-research run; scheduled jobs start it in the agent as before.
   `turn_timing.gate_call_ms` is the call's own time, `gate_ms` what the turn
   waited. First local turns saved under 0.1 s (preparation is short without
   attachments or compaction).
2. A yes comes with 1-3 queries, each anchored in time (month and year, or the
   year). `prefetch_messages()` runs `research` with them and appends the call
   and its result to the turn, so the chat model starts from current pages and
   the grounding check judges them like any turn's sources. The stream sends
   `tool_start`/`tool_end` for it, so the client shows "Researching".
3. A failed lookup is re-labelled (`LOOKUP_FAILED_NOTE`): say that current
   information could not be looked up, never present memory as current (the
   research error itself says "answer from what you know").
4. When the user disputes a fact (`disputed`), the research result also carries
   `DISPUTE_NOTE`: decide from the sources, not the user's confidence - keep a
   correct answer politely without apologising, correct a wrong one plainly.
   A lookup alone still ended in agreement with a user who was wrong
   (`fresh_pushback_holds` 1 of 3 before, 3 of 3 after). A disputed fact is
   always looked up: `disputed` with queries means a lookup even when the gate
   said `lookup=false`, and without queries the turn carries no dispute. The
   Nov 1 2026 audit found 102 of 125 disputed turns had run no lookup, so the
   note never reached the model - and most of them were not disputes at all
   (the user clarifying what they meant, or telling the assistant about their
   own life, or about a film plot). The prompt now keeps `disputed` for facts
   about the world that sources can settle.
5. The gate sees whether the latest message has attachments (images, PDFs,
   media; text files arrive as text). A question the attachment answers - a
   photo of opening hours, a receipt, a screenshot - is read, not looked up
   (`cz_image_reading` looked the opening hours up on the web in 2-3 of 4
   runs).

Why before the turn and not after a draft: the chat model streams tokens to the
client as it writes, and (when this was built) it ran on a Gemini context cache
whose tools and tool config could not change per request, so it could neither
be forced to call a tool nor have a streamed draft taken back.

Where it runs: every chat (anonymous included) that has `research` bound -
standing chats (the user writing in an agent, sports or language chat) too;
never unattended agent runs, the planner or `delegate_task` subagents
(`ChatAgent.freshness_gate`). It fails open: an error, or no answer within
`FRESHNESS_GATE_TIMEOUT_SECONDS` (wall clock; the API deadline itself is floored
at `GEMINI_MIN_REQUEST_DEADLINE_SECONDS`), means the turn goes ahead without it.
Its call is priced at its own model (`usage_info["freshness_usage"]`,
`calculate_freshness_cost()`). Log line: "Freshness gate" with `lookup`,
`queries`, `reason`.

## Thinking level per turn

The gate's call also picks the turn's `thinking`: `high` when a good answer
needs careful reasoning or a plan (product or place recommendations, trip or
training plans, multi-source research, maths/data/code/files, real trade-offs,
a disputed fact), `medium` for other several-part tasks (a short plan or
how-to, a lookup to put together, a follow-up that changes a plan, a
multi-step action on the user's data, a lasting correction of how to reply),
`low` for the rest - chit-chat, quick facts, short follow-ups, rewriting or
translating, a single simple action. A lasting correction ("from now on",
"always", "stop doing X") went `medium` on Nov 23 2026: at `low` the model
sometimes said it had suggested the instructions card without calling
`propose_instruction_change` (`instructions_style_rule` 5/10 at `low`, 10/10
at `medium`, then 10/10 with the gate choosing `medium` itself). Single data
actions stay `low`: the six Todoist/Calendar action cases called their tool on
18/18 runs at `low`, and in production (Nov 9-23) replies claiming an action
("přidal", "added"...) without a data tool were as rare at `low` (6 of 449
turns) as at `medium` (2 of 192) and `high` (1 of 89) - a regex count, an
upper bound.
`low` turns run on `ChatAgent.light_graph` at
`FRESHNESS_GATE_LIGHT_THINKING_LEVEL`, `high` ones on `ChatAgent.deep_graph`
at `FRESHNESS_GATE_DEEP_THINKING_LEVEL` when it is set, and `medium` ones on the model's own
(`"thinking_level": "medium"` on Hydrogen's `MODELS` entry; `_turn_graph()`).
Since Nov 26 2026 the deep level is empty, so `high` turns also run at the
model's own: `medium` on Hydrogen, the API default on Carbon (no
`thinking_level` on its entry), which is where complex research goes by
choice. Two weeks on Hydrogen (Nov 12-25, 821 turns) had `high` on 12% of
chat turns at $0.194 a turn and a median 56 s - a third of the chat spend -
against `medium`'s $0.080 and 19 s; the Nov 23 A/B of the 8 gate-`high` eval
cases at `medium` scored 14/16 against 15/16 for 33% less. The gate still
returns `high` and logs it, so `thinking` in `turn_timing` keeps the verdict,
not the level the turn ran at.
A gate that errors, times out or answers unparsed leaves `thinking` unset,
which runs the model's own level, as do the places the gate does not run (agent
runs, the planner). Standing chats never go light but can go deep. The gate's log line
carries `thinking`, and so does "Chat turn completed and saved" (from the
turn's `usage_info`), which has the `message_id` to join the cost row.

Why three levels (Nov 12 2026): on Gemini 4 Hydrogen, whose API default is
`high`, the first 13 turns cost ~3x 3.8 Flash's per turn, with 3-6x the output
(thinking included) on tool turns - and the 24% of turns the two-way gate
judged hard are the expensive ones. A probe on three prompts (easy / a dinner
plan / a family trip plan): `low` 28 / 619 / 1515 thinking tokens, `medium`
72 / 1251 / 2713, `high` 70 / 1414 / 3235 - `low` is the big step, `medium`
saves 10-20% against `high`.

Why (Oct 25 2026): plain Flash turns went from ~7 s to ~12 s overnight on Oct
5-6 with no deploy - the time per output token (thinking included) doubled,
apparently on the provider's side; the gate itself takes ~0.9 s (median, 0
timeouts in a week). A probe on 3.8 Flash: default thinking (in effect
"high") 9.6 s to the first word and 12.9 s in total, `low` 1.9 s and 5.6 s,
"medium" no faster than default, "minimal" unsupported. On the eval suite, low
thinking everywhere cut plain-turn time by a third and agent cost by a
quarter, but skipped the product-research skill (1 of 4 vs 3 of 4) and
delegation on hard cases - hence the per-turn choice instead of a global
setting.

Measured in prod (Nov 1 2026, the week before vs the week after, 992 vs 644
turns): the gate judged 83% of turns easy. The median plain turn (no tools,
no lookup) went from 10.5 s to 7.6 s (p90 24.2 s to 16.5 s), and the
median of all turns from 13.1 s to 10.0 s. Easy plain turns take 7.3 s,
hard ones 14.2 s. `load_skill` ran on 1.7% of turns before and 1.9% after.
`delegate_task` ran on none in either week, so there was no delegation to
miss.

### Re-measured Nov 14 2026

From the "Freshness gate" journal lines (Oct 18 - Nov 14, 2,589 decisions)
and `message_costs.tools_used` (the prefetched `research` round counts there,
so "the model searched itself" = web turns minus gate lookups):

| | Oct 18-31 | Nov 1-12 | Nov 13-14 |
|---|---|---|---|
| Chat turns | 1,527 | 916 | 146 |
| Gate lookups | 15% | 10% | 5% |
| The model searched itself | 11% | 9% | 14% |
| Disputed turns (of them without a lookup) | 130 (106) | 10 (2) | 0 |
| Timeouts | 0 | 1 | 0 |

- **Disputed facts are now checked**: 106 of 130 disputed turns ran no lookup
  before the Nov 1 fix, 2 of 10 after (a disputed verdict with no queries).
  Narrowing `disputed` to facts about the world made it ten times rarer.
- **Attachments do not trigger lookups**: 14 lookups on 257 turns with an
  image since Nov 1 (5%, matched to the gate line by time).
- **Open: fewer gate lookups since the thinking choice joined the gate**
  (Nov 13). Web use stays near 18% of turns, but the chat model now runs the
  search itself more often - an extra round, without the gate's dated
  queries. Two days are too few to act on; re-measured ~Nov 21 (TODO.md).

### Re-measured Nov 20 2026

From `message_costs` (`turn_timing.gate_lookup`, `tools_used`; Hydrogen chat
turns) and the "Freshness gate" journal lines, Nov 15-20:

| | Nov 1-12 | Nov 13-14 | Nov 15-20 |
|---|---|---|---|
| Chat turns | 916 | 146 | 487 |
| Gate lookups | 10% | 5% | 14% |
| The model searched itself | 9% | 14% | 18.5% |
| Disputed turns (of them without a lookup) | 10 (2) | 0 | 8 (2) |
| Timeouts | 1 | 0 | 5 |

- **The gate's lookups recovered**: the 5% was two days of noise, not the
  thinking choice.
- **The model searches on its own more**: 90 turns where the gate ran no
  lookup and the chat model then called `web_search`, `research` or
  `fetch_url` (29 at low thinking, 36 medium, 22 high). About two thirds are
  turn 4 or later of a thread about choosing or buying specific products
  (lighting, bike parts, tools), where the message alone reads as a remark
  ("I can't put a dimmer under the switch") but the answer needs specs and
  prices. The gate logged an empty `reason` on most of its no-lookup
  decisions, so the reasons do not explain them.
- **Timeouts**: all 5 on Nov 19 between 15:47 and 17:55 (3.0 s limit), which
  reads as one slow afternoon at the provider; watch the count.

### Product threads are looked up (Nov 20 2026)

The week's 467 gate inputs (the user's message and the head of the previous
reply) were replayed through the gate, once per prompt. Its reasons showed
the cause: it filed "recommend a thermostatic shower mixer", "a matched set
from one maker" and "give me a link" under timeless advice or a stated
preference, although "current products, specs, prices" was already on the
lookup list.

| Gate looked up on | Old prompt | New prompt |
|---|---|---|
| 89 turns where the chat model searched itself | 13 | 35 |
| 308 turns with no web use | 5 | 7 |
| 70 turns where the gate had looked up | 56 | 63 |

- The prompt now says that recommending, comparing, choosing or finding
  specific products, services, shops, events or places is never timeless;
  that a follow-up adding a constraint, a measurement, a preference or a
  doubt while the previous reply names products is looked up; and that any
  request for a link or to find something is a lookup. Accepting, thanking,
  reporting what one owns and asking for a summary stay without one.
- **The gate is noisy at the boundary**: replaying the old prompt reproduced
  only 56 of its own 70 lookups and fired on 13 turns it had skipped, so
  small differences between weeks are not signal.
- Of the remaining 54 model-searched turns many are not the gate's to catch
  (a TV plot, a pet's diet, edits of a post); the rest were not read one by
  one under the new prompt.
- Side effect: the thinking choice moved with it, 90 `high` verdicts against
  75 on the same turns, since product follow-ups now read as choosing
  products.
- Evals: `fresh_product_followup` and `fresh_gate_precision_product_thanks`
  assert the gate's own decision (`expect.gate_lookup`); all `fresh_*` cases
  passed twice bar one live-web failure.

**Re-measured Nov 27 2026** (`message_costs` chat turns, Nov 15-19 against
Nov 21-27). A gate lookup is stored as a `research` call in `tools_used`, so
the chat model's own web turns are web-tool turns minus lookup turns.

| | Nov 15-19 | Nov 21-27 |
|---|---|---|
| Chat turns | 462 | 430 |
| Gate lookups | 69 (14.9%) | 60 (14.0%) |
| Chat model searched itself | 93 (20.1%) | 58 (13.5%) |
| `high` thinking | 70 (15.2%) | 42 (9.8%) |
| Average cost, `high` / other | $0.189 / $0.058 | $0.233 / $0.057 |
| `gate_ms` median / p90 | 809 / 1,065 | 726 / 900 |
| "Freshness gate timed out" | 5 (all Nov 19) | 1 (Nov 24) |

- The replay's predicted rise in lookups (74 -> 105) did not show; the rate
  held at 14%. The chat model searched on its own a third less, so the
  turns the gate misses shrank, but the traffic changed with the week too
  (the noise note above applies).
- `high` turns fell by a third and cost more each; total `high` spend went
  down ($13.20 -> $9.77).
- Idle lookups (looked up, then nothing used) cannot be read from
  `tools_used`, since the lookup itself is the `research` entry; it would
  need the reply's sources. Not pursued: lookups did not grow.
- No trigger in either direction: the follow-up clause stays, and the gate
  keeps the first 1,200 characters of the previous reply.

## Dated search results

Providers' publish dates ride on each `web_search` result as `published`
(YYYY-MM-DD; Brave `page_age`, Tavily `published_date`, Exa `publishedDate`;
Linkup and ddgs give none). When results carry dates and none is from the last
`WEB_SEARCH_RECENT_DAYS`, the result gets a `_recency` note: search again with
the month and year before answering, and do not present these as current.

Since the providers in use give no dates, every fetched page that declares
itself an article (trafilatura metadata, `pagetype == "article"`) starts with
`Published: YYYY-MM-DD` ([page_date.py](../../src/agent/tools/page_date.py)),
in research and fetch_url results alike. Other pages get no date: Wikipedia
and hubs only carry creation or copyright years. `SourcePage.published` reads
the line back for the grounding check's age rule.

## Snippets are not verification

`GROUNDING_DIRECTIVE` on every `web_search` result now also says: never call
something verified or confirmed, or quote a page, unless you read it
(`research`). The [grounding check](grounding.md) also treats a sentence that
says it verified something as a claim.

## Grounding covers recent news

The verifier prompt lists RECENT NEWS facts from the last 12 months before
TODAY as claims - what was announced, launched, approved or decided and when,
who holds a role now, where a new product is available. History and events
older than 12 months stay out of scope (the Oct 3 noise lesson).

## Configuration

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `FRESHNESS_GATE_ENABLED` | `true` | Kill switch (tests and the E2E server set it to `false`) |
| `FRESHNESS_GATE_MODEL` | `gemini-3.5-flash-lite` | The gate's model (priced only) |
| `FRESHNESS_GATE_TIMEOUT_SECONDS` | `3` | Wall-clock cap; past it the turn goes on without the gate |
| `FRESHNESS_GATE_MAX_QUERIES` | `3` | Queries the prefetched research runs |
| `FRESHNESS_GATE_LIGHT_THINKING_LEVEL` | `low` | Thinking level for turns the gate judges low; empty = those at the model's own |
| `FRESHNESS_GATE_DEEP_THINKING_LEVEL` | empty | Thinking level for turns the gate judges high; empty = those at the model's own (medium on Hydrogen, Nov 26 2026) |
| `WEB_SEARCH_RECENT_DAYS` | `365` | No dated result newer than this: the `_recency` note |

## Testing

- Unit: [test_freshness.py](../../tests/unit/test_freshness.py) (gate decision,
  fail-open, deadlines, prefetch, failed-lookup note),
  [test_freshness_agent.py](../../tests/unit/test_freshness_agent.py) (stream
  and batch wiring, events, cost, the light graph for easy turns),
  [test_web_search_tool.py](../../tests/unit/test_web_search_tool.py)
  (`_recency`, directive), [test_search_provider.py](../../tests/unit/test_search_provider.py)
  (`published`), [test_grounding_check.py](../../tests/unit/test_grounding_check.py)
  (dated verifier prompt).
- Evals: `fresh_keynote_followup`, `fresh_office_holder`,
  `fresh_pushback_holds`, `fresh_gate_precision` (the gate must not fire on a
  translation), `fresh_opinion_current_politics` (advice about current
  politics looks up who leads which party now). Evals search with ddgs only, which gives no dates and is
  sometimes blocked from a machine after many runs ("No results found") - a
  run with a blocked ddgs measures the failed-lookup path, not the gate.

## See Also

- [Grounding Check](grounding.md)
- [Agent Tools](agent-tools.md) - web tools, provider chain
- [Agent Graph](../architecture/agent-graph.md)
