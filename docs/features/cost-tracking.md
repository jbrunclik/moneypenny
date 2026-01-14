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
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    image_generation_cost_usd REAL,
    created_at TEXT NOT NULL
);
```

**Note**: `delete_conversation()` intentionally preserves cost data for accurate reporting.

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

Calculated from `usage_metadata` with separate pricing for prompt tokens and candidate/thought tokens. Stored separately in `image_generation_cost_usd` column.

### Other Tools

Web search and URL fetching are free (no cost tracking).

## Currency Rate Updates

Currency exchange rates are stored in the database (`app_settings` table) and updated daily via a systemd timer.

### Automatic Updates (systemd timer)

- Runs daily at 4:00 AM (with up to 30 min random delay)
- Fetches rates from [open.er-api.com](https://open.er-api.com) (free, no API key required)
- Updates rates for USD, CZK, EUR, GBP
- Automatically enabled when running `make deploy`
- View logs: `journalctl --user -u ai-chatbot-currency`

### Manual Update

```bash
make update-currency  # Fetch and update rates immediately
```

### Fallback Behavior

- If DB has no rates (first run), falls back to hardcoded defaults in `Config.CURRENCY_RATES`
- If API fetch fails, existing rates are preserved
- Rates are loaded fresh from DB on each currency conversion (no app restart needed)

## Configuration

```bash
# .env
COST_CURRENCY=CZK  # Display currency (default: CZK)
```

```python
# src/config.py
MODEL_PRICING = {
    "gemini-3-flash-preview": {
        "input": 0.30,   # Per million tokens
        "output": 1.20,  # Per million tokens
    },
    # ... other models
}

CURRENCY_RATES = {
    "USD": 1.0,
    "CZK": 23.0,  # Fallback if DB has no rates
    "EUR": 0.92,
    "GBP": 0.79,
}

COST_HISTORY_MAX_MONTHS = 120      # Maximum months for cost history queries
COST_HISTORY_DEFAULT_LIMIT = 12    # Default months returned
STREAM_CLEANUP_THREAD_TIMEOUT = 600  # Timeout for cleanup thread (seconds)
STREAM_CLEANUP_WAIT_DELAY = 1.0      # Delay before checking if message was saved
```

## Key Files

### Backend

- [costs.py](../../src/utils/costs.py) - Cost calculation and currency conversion utilities
- [config.py](../../src/config.py) - Model pricing and currency rates
- [models.py](../../src/db/models.py) - Cost CRUD methods
- [chat_agent.py](../../src/agent/chat_agent.py) - Token usage extraction from `usage_metadata`
- [tools/image_generation.py](../../src/agent/tools/image_generation.py) - Image generation tool includes `usage_metadata` in response
- [api/utils.py](../../src/api/utils.py) - `calculate_and_save_message_cost()`, `calculate_image_generation_cost_from_tool_results()`
- [routes/costs.py](../../src/api/routes/costs.py) - Cost API endpoints

### Frontend

- [main.ts](../../web/src/main.ts) - `updateConversationCost()` updates cost display after messages
- [CostHistoryPopup.ts](../../web/src/components/CostHistoryPopup.ts) - Cost history popup component
- [MessageCostPopup.ts](../../web/src/components/MessageCostPopup.ts) - Message cost popup component
- [ImageGenPopup.ts](../../web/src/components/ImageGenPopup.ts) - Image generation popup (shows image generation cost)
- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Monthly cost display in footer
- [Messages.ts](../../web/src/components/Messages.ts) - Cost button rendering in message actions

### Systemd

- [update_currency_rates.py](../../scripts/update_currency_rates.py) - Python script that fetches and saves rates
- [ai-chatbot-currency.service](../../systemd/ai-chatbot-currency.service) - Systemd service (oneshot)
- [ai-chatbot-currency.timer](../../systemd/ai-chatbot-currency.timer) - Daily timer

## API Endpoints

- `GET /api/messages/<message_id>/cost` - Get cost for a single message
- `GET /api/conversations/<conv_id>/cost` - Get total cost for a conversation
- `GET /api/users/me/costs/monthly` - Get current month cost
- `GET /api/users/me/costs/history?limit=12` - Get monthly cost history

## See Also

- [Image Generation](file-handling.md#image-generation) - Image generation costs
- [Database Schema](../architecture/database.md) - Cost table schema
- [Testing Guide](../testing.md) - Testing cost tracking
