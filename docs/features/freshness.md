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
   (`fresh_pushback_holds` 1 of 3 before, 3 of 3 after).

Why before the turn and not after a draft: the chat model streams tokens to the
client as it writes, and it runs on a Gemini context cache whose tools and tool
config cannot be changed per request, so it can neither be forced to call a
tool nor have a streamed draft taken back.

Where it runs: regular chats (anonymous included) that have `research` bound;
never autonomous agents, programs, the planner or `delegate_task` subagents
(`ChatAgent.freshness_gate`). It fails open: an error, or no answer within
`FRESHNESS_GATE_TIMEOUT_SECONDS` (wall clock; the API deadline itself is floored
at `GEMINI_MIN_REQUEST_DEADLINE_SECONDS`), means the turn goes ahead without it.
Its call is priced at its own model (`usage_info["freshness_usage"]`,
`calculate_freshness_cost()`). Log line: "Freshness gate" with `lookup`,
`queries`, `reason`.

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
| `WEB_SEARCH_RECENT_DAYS` | `365` | No dated result newer than this: the `_recency` note |

## Testing

- Unit: [test_freshness.py](../../tests/unit/test_freshness.py) (gate decision,
  fail-open, deadlines, prefetch, failed-lookup note),
  [test_freshness_agent.py](../../tests/unit/test_freshness_agent.py) (stream
  and batch wiring, events, cost),
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
