# Cost Tracking

The app tracks API costs per conversation and per user per calendar month, accounting for token usage and image generation.

## Overview

Cost tracking provides:
- Per-conversation cost totals
- Per-user monthly cost aggregation
- Per-message cost breakdown
- Separate tracking for image generation costs
- Currency conversion for display
- Cost history with monthly breakdown

## How It Works

### 1. Token Usage Tracking

Token counts are extracted from `usage_metadata` in LangChain's `AIMessage` and `AIMessageChunk` objects (both batch and streaming modes).

**Memory efficiency:**
Token usage is tracked efficiently during streaming by extracting and accumulating counts immediately from each chunk, rather than storing entire message objects. Only the final token counts are kept in memory.

### 2. Image Generation Costs

Image generation costs are calculated from `usage_metadata` returned by the Gemini image generation API.

Costs are calculated with separate pricing for:
- Prompt tokens (input)
- Candidate/thought tokens (output)

Stored separately in `image_generation_cost_usd` column for display in image generation popup.

### 3. Cost Calculation

Costs are calculated using model pricing from [config.py](../../src/config.py) and converted to the configured currency (default: CZK).

**Currency conversion:**
- Costs are stored in USD
- Converted to display currency on retrieval
- Currency rates updated daily via systemd timer

### 4. Database Storage

Costs are stored in the `message_costs` table:

```sql
CREATE TABLE message_costs (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL,
    image_generation_cost_usd REAL DEFAULT 0.0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,  -- subset of input_tokens
    tool_rounds INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    tool_errors INTEGER NOT NULL DEFAULT 0,
    tools_used TEXT,       -- JSON list
    job_id TEXT,           -- the standing job that ran the turn, if any
    stopped_by TEXT,       -- the turn budget that stopped it, if any
    turn_timing TEXT       -- JSON phase timings (freshness gate, model calls)
);
```

**Note**: `delete_conversation()` intentionally preserves cost data for accurate reporting.

### Side calls (`side_costs`, from Nov 15 2026)

Model calls outside a chat turn record their spend in `side_costs` (`feature`,
`model`, tokens, `cost_usd`, `user_id` when known) through
[`record_side_cost`](../../src/services/side_costs.py), which takes either SDK's
usage and never raises into the call: `title`, `program_review`,
`instructions_review`, `ai_assist`, `compaction`, `memory_review`,
`memory_defrag` (the nightly script) and `memory_summary`. The freshness gate
and the grounding check are part of the turn's cost already. Embeddings are not
recorded yet (priced per character, a few cents a month). The admin page adds
them to the family totals and lists them per feature (Nov 16 2026,
[admin.md](admin.md)).

### Flex tier (Nov 17 2026)

Gemini's Flex tier bills `FLEX_PRICE_RATIO` (0.5) of the standard price for
calls that can wait: it queues them (a tiny Hydrogen call took 48-84 s, a
memory review 57-157 s), may refuse under load, and never upgrades itself.
`generate_on_flex` ([src/agent/flex.py](../../src/agent/flex.py)) asks for
`service_tier=flex` with a `FLEX_TIMEOUT_SECONDS` (600) client timeout and runs
the call again on standard on 429, 503, 504 or a timeout ("Flex call fell
back", with `reason` and `waited_ms`). The tier that served a call comes from
the `x-gemini-service-tier` response header (`served_tier`; usage_metadata
does not carry it), so a fallback is priced at the standard rate;
`side_costs.service_tier` is 'flex' for Flex rows and NULL otherwise.

The background memory review (`MEMORY_REVIEW_FLEX`) and the nightly memory
defrag (`MEMORY_DEFRAG_FLEX`, Carbon; its call moved from LangChain to the SDK
with `DefragPlan` as `response_schema`, Nov 17 2026) use it. A first Carbon
probe hit a 504 after 179 s: the SDK sends the client timeout as
`X-Server-Timeout`, so the server gave up at the shared client's 180 s - with
`FLEX_TIMEOUT_SECONDS` Carbon on Flex answered in 5-9 s. Not evals: the agent
runs through LangChain, which cannot send the tier, and the judge is ~6% of a
run's cost (a smoke run's judge: $0.08 of $1.28), not worth a queue on every
case. Batch (up to 24 h) fits none of them.

Thinking level: side calls go through `chat_model()`
([gemini_clients.py](../../src/agent/gemini_clients.py)), which sends no
thinking level unless asked - and Gemini 4 Hydrogen's API default is high. Each
Hydrogen side call names its own (Nov 16 2026, measured live on the same
prompts): `AI_ASSIST_THINKING_LEVEL` and `DEEP_RESEARCH_FOLLOWUP_THINKING_LEVEL`
are `low` (same crons, prompts and follow-up questions, 1.5-2x faster, ~60%
fewer output tokens); `PROGRAM_REVIEW_THINKING_LEVEL` and
`INSTRUCTIONS_REVIEW_THINKING_LEVEL` stay `high` - at low the instructions review
left out the new text a `move_to_instructions` suggestion needs in 5 of 6 runs,
so the suggestion was dropped, and medium was no faster or cheaper than high.
Compaction and the memory review set low through the google-genai SDK directly;
titles, the gate and the grounding check run on Flash-Lite.

## UI Display

### Conversation Cost

Shown under the input box, updates after each message.

### Monthly Cost

Shown in the sidebar footer, clickable to view cost history.

### Cost History Popup

Shows monthly breakdown with total cost.

### Message Cost Button

Dollar icon appears on assistant messages, opening a popup with:
- Token counts (input/output)
- Token costs
- Image generation cost (if applicable)
- Total cost
- Model used

### Image Generation Popup

Shows the cost of image generation only (excluding prompt tokens).

## Cost Calculation Details

### Token Costs

Calculated from `input_tokens` and `output_tokens` using per-million-token pricing:

```python
input_cost = (input_tokens / 1_000_000) * model_price_per_million_input
output_cost = (output_tokens / 1_000_000) * model_price_per_million_output
total_token_cost = input_cost + output_cost
```

### Image Generation Costs

Calculated from `usage_metadata` with three rates: prompt tokens at the input rate, image output tokens (`image_output_token_count`, from the IMAGE entry of `candidates_tokens_details`) at `image_output` ($120/M, ~$0.134 per 1K image), and remaining text + thinking output at `output` ($12/M). Without a modality breakdown, all candidate tokens are billed as image output. Stored separately in `image_generation_cost_usd` column.

### Other Tools

Web search runs on provider free tiers (Brave, Exa, Linkup, Tavily, then
ddgs), counted against monthly quotas (`SEARCH_QUOTA_*_MONTHLY`) rather than
priced per turn. Pages read through the Exa fallback (403/429, PDFs) bill
about $0.001 each into Exa's counter, logged as "Page read via fallback" with
`cost_usd` ([web-reading spec](../superpowers/specs/2026-11-15-web-reading-design.md)).
None of this is in `message_costs`.

## Prompt Caching & Known Limitations

Long conversations (especially program conversations and multi-round tool turns)
re-send a large stable prefix on every LLM call. A few durable facts govern how
caching affects tracked cost:

- **Gemini 4 caches implicitly only.** Its API rejects `caches.create` (400).
  Chats use a split layout so the prefix stays stable - the profile's static
  prompt (`CacheProfile` in [prompts.py](../../src/agent/prompts.py)) as the
  leading SystemMessage, tools bound, the per-turn `[CONTEXT]` just before the
  user message, mid-turn guidance as a wrapped HumanMessage
  (`tool_round_check.py`) - and Gemini caches it implicitly at the
  `cached_input` rate. A Nov 12 2026 probe: two requests sharing a 32k-token
  prefix and differing at the end hit 30k cached tokens on all three Gemini 4
  models. (On Gemini 3 implicit caching never hit - 0 of 7 requests in a Nov 7
  2026 probe - and an explicit context cache did the saving; that code path was
  removed in Nov 2026 once both chat models were Gemini 4.)
- **Cached tokens are recorded and discounted.** Cache hits are read from
  `usage_metadata.input_token_details.cache_read`, aggregated as
  `cached_input_tokens` in `usage_info`, and billed at the model's `cached_input`
  price in `calculate_token_cost()` ([src/services/costs.py](../../src/services/costs.py)).
  `input_tokens` from the API already *includes* the cached subset; the cost code
  splits it into cached/uncached rather than double-counting. (Earlier builds did
  not record `cache_read` and therefore overstated cost — that gap is closed.)
- **Streaming usage is delta-encoded.** `input_tokens` and `cache_read` arrive
  once per LLM call (not per chunk), so summing usage across streamed chunks and
  across messages in a turn is correct and does not double-count.
- **Fixed per-round overhead.** Each tool round re-sends the system prompt plus the
  full tool-schema declarations. Even at the implicit-cache rate, a turn with N
  sequential tool rounds pays this fixed overhead N times — the main reason
  multi-round tool turns dominate cost.

### Per-turn cost after the prompt cuts (Nov 20 2026)

The Nov 14 cuts took a minimal live call from 23,435 to 17,217 input tokens
(tool manuals moved into skills or onto tool results, duplicate prompt
sections removed). Measured a week later from `message_costs` (Hydrogen chat
turns, no job runs):

| | To Nov 14 | Nov 17-20 |
|---|---|---|
| All turns: cost | $0.0717 (149 turns) | $0.0686 (262 turns) |
| All turns: input / cached | 73.2k / 37.3k (51%) | 66.9k / 34.9k (52%) |
| No-tool turns: cost | $0.0454 (100 turns, Nov 12-14) | $0.0361 (134 turns) |
| No-tool turns: input, cached share | 35.1k, 29% | 26.1k, 30% |

- No-tool turns show the cut cleanly: 26% fewer input tokens, 20% cheaper.
- Across all turns the gain is 4%: history length and tool rounds dominate
  (Nov 15-16 averaged $0.0824 at 1.25 rounds on two long product threads).
- The smallest first call of a day was 19.7k-23.1k tokens (`turn_timing.calls`,
  from Nov 15): a real turn adds the `[CONTEXT]` block and memories to the
  17.2k floor.
- The cached share did not move: 30% on no-tool turns, 20% on the first call
  of all turns. A shorter `[CONTEXT]` (Nov 16) saves tokens, not cache misses.

## Currency Rate Updates

Currency exchange rates are stored in the database (`app_settings` table) and updated daily via a systemd timer.

### Automatic Updates (systemd timer)

- Runs daily at 4:00 AM (with up to 30 min random delay)
- Fetches rates from [open.er-api.com](https://open.er-api.com) (free, no API key required)
- Updates rates for USD, CZK, EUR, GBP
- Automatically enabled when running `make deploy`
- View logs: `journalctl --user -u moneypenny-currency`

### Manual Update

```bash
make update-currency  # Fetch and update rates immediately
```

### Fallback Behavior

- If DB has no rates (first run), falls back to hardcoded defaults in `Config.CURRENCY_RATES`
- If API fetch fails, existing rates are preserved
- Rates are loaded fresh from DB on each currency conversion (no app restart needed)

## Price Changes (Nov 2026)

A cost is calculated once, when the message is saved, and stored; the charts,
the admin overview and the daily spend warning all read the stored values. So a
provider price change only has to apply from its effective instant on:
`get_model_pricing(model, at=None)` starts from `MODEL_PRICING` and applies every
`MODEL_PRICING_CHANGES` entry in force at `at` (now when omitted). Add a known
future change there ahead of time - no deploy on the day - and keep
`MODEL_PRICING` as the rates before the first change, so older costs and tests
that pin a date stay right. Tests that assert a rate pin the clock
(`src.utils.clock._now`), or they break on the switch date.

## Configuration

```bash
# .env
COST_CURRENCY=CZK  # Display currency (default: CZK)
```

```python
# src/config.py
MODEL_PRICING = {
    "gemini-4-hydrogen": {
        "input": 1.50,         # Per million tokens
        "cached_input": 0.075,
        "output": 7.50,        # Per million tokens (thinking included)
    },
    # ... other models
}

# Dated changes, in date order: from that instant, get_model_pricing() applies them
MODEL_PRICING_CHANGES = {
    "gemini-4-carbon": [
        (datetime(2026, 12, 1, tzinfo=UTC), {"input": 4.00, "cached_input": 0.20, "output": 20.00}),
    ],
}

CURRENCY_RATES = {
    "USD": 1.0,
    "CZK": 23.0,  # Fallback if DB has no rates
    "EUR": 0.92,
    "GBP": 0.79,
}

COST_HISTORY_MAX_MONTHS = 120      # Maximum months for cost history queries
COST_HISTORY_DEFAULT_LIMIT = 12    # Default months returned
STREAM_CLEANUP_THREAD_TIMEOUT_SECONDS = 600  # Timeout for cleanup thread (seconds)
STREAM_CLEANUP_WAIT_DELAY_SECONDS = 1.0      # Delay before checking if message was saved
```

## Key Files

### Backend

- [costs.py](../../src/services/costs.py) - Cost calculation and currency conversion utilities; `calculate_and_save_message_cost()` and the per-component helpers (`calculate_image_generation_cost_from_tool_results()`, delegate, grounding, freshness, deep research)
- [config.py](../../src/config.py) - Model pricing and currency rates
- [models/](../../src/db/models/) - Cost CRUD methods
- [turn_usage.py](../../src/agent/turn_usage.py) - Token usage extraction from `usage_metadata`
- [tools/image_generation.py](../../src/agent/tools/image_generation.py) - Image generation tool includes `usage_metadata` in response
- [routes/costs.py](../../src/api/routes/costs.py) - Cost API endpoints

### Frontend

- [toolbar.ts](../../web/src/core/toolbar.ts) - `updateConversationCost()` updates cost display after messages
- [CostHistoryPopup.ts](../../web/src/components/CostHistoryPopup.ts) - Cost history popup component
- [MessageCostPopup.ts](../../web/src/components/MessageCostPopup.ts) - Message cost popup component
- [ImageGenPopup.ts](../../web/src/components/ImageGenPopup.ts) - Image generation popup (shows image generation cost)
- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Monthly cost display in footer
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Cost button rendering in message actions

### Systemd

- [update_currency_rates.py](../../scripts/update_currency_rates.py) - Python script that fetches and saves rates
- [moneypenny-currency.service](../../systemd/moneypenny-currency.service) - Systemd service (oneshot)
- [moneypenny-currency.timer](../../systemd/moneypenny-currency.timer) - Daily timer

## API Endpoints

- `GET /api/messages/<message_id>/cost` - Get cost for a single message
- `GET /api/conversations/<conv_id>/cost` - Get total cost for a conversation
- `GET /api/users/me/costs/monthly` - Get current month cost
- `GET /api/users/me/costs/history?limit=12` - Get monthly cost history

## See Also

- [Image Generation](image-generation.md) - Image generation costs
- [Database Schema](../architecture/database.md) - Cost table schema
- [Testing Guide](../testing.md) - Testing cost tracking
