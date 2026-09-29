# WhatsApp Integration (Autonomous Agents)

The WhatsApp integration enables autonomous agents to send notifications to users via WhatsApp. This is useful for agents that run on schedules and need to report results.

## Overview

1. **Business-Initiated Messaging**: Uses Meta's WhatsApp Cloud API with template messages
2. **Per-User Configuration**: Each user configures their WhatsApp phone number in Settings
3. **Agent Tool**: The `whatsapp` tool is available to autonomous agents when configured
4. **Permission Gating**: Tool only appears when app-level WhatsApp is configured AND user has set their phone number

## Prerequisites

1. **Meta Business Account**: Register at [business.facebook.com](https://business.facebook.com)
2. **WhatsApp Business Platform**: Create an app at [developers.facebook.com](https://developers.facebook.com)
3. **System User Token**: Generate a permanent access token (not the 24h temporary token)
4. **Message Template**: Create and get approval for a template with two variables

## Configuration

```bash
# .env

# Phone Number ID from WhatsApp API Setup (numeric ID, NOT the phone number)
WHATSAPP_PHONE_NUMBER_ID=982966681562240

# Permanent System User access token
WHATSAPP_ACCESS_TOKEN=EAATly...

# Approved template name (must have TWO variables: {{1}}=agent name, {{2}}=message)
WHATSAPP_TEMPLATE_NAME=agent_notification

# Optional: Public app URL for conversation links in messages
APP_URL=https://chat.example.com

# Optional: API timeout (default: 10 seconds)
WHATSAPP_API_TIMEOUT=10

# Optional: Max message length before truncation (default: 1024 - WhatsApp template limit)
WHATSAPP_MAX_MESSAGE_LENGTH=1024
```

## Message Template Setup

Create a template in Meta Business Suite → WhatsApp Manager → Message Templates:

1. **Template Name**: e.g., `agent_notification`
2. **Category**: Utility
3. **Language**: English
4. **Body**: Must contain exactly TWO variables:
   ```
   {{1}}:

   {{2}}
   ```
   - `{{1}}` = Agent name (e.g., "Daily Briefing Agent")
   - `{{2}}` = Message content (max 1024 characters)

5. Submit for approval (typically approved within minutes for utility templates)

## User Configuration

Users configure their WhatsApp phone number in the Settings popup:

1. Open Settings (gear icon)
2. Enter phone number in E.164 format (e.g., `+1234567890`)
3. Save

The phone number is validated:
- Must start with `+` followed by 1-15 digits
- No spaces, dashes, or other characters

## WhatsApp Tool

The `whatsapp` tool is available to autonomous agents when:
- App-level WhatsApp configuration is complete (all env vars set)
- User has configured their WhatsApp phone number

**Tool Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `message` | string | required | Message content (Markdown supported, auto-converted) |
| `include_conversation_link` | bool | true | Append link to the conversation |

**Example agent prompt:**
```
After completing the analysis, send a summary via WhatsApp.
```

## Markdown Conversion

Messages containing Markdown are automatically converted to WhatsApp-compatible formatting:

| Markdown | WhatsApp | Notes |
|----------|----------|-------|
| `**bold**` | `*bold*` | Bold text |
| `# Header` | `*Header*` | Headers become bold |
| `[text](url)` | `text (url)` | Links show URL in parentheses |
| `![alt](url)` | `[Image: alt]` | Images show alt text |
| `` `code` `` | `code` | Inline code backticks removed |
| ` ```code``` ` | ` ```code``` ` | Code blocks preserved |
| `---` | `───` | Horizontal rules |

## Key Files

**Backend:**
- [tools/whatsapp.py](../../src/agent/tools/whatsapp.py) - WhatsApp tool and API client
- [tools/context.py](../../src/agent/tools/context.py) - Agent name context for messages
- [routes/settings.py](../../src/api/routes/settings.py) - User phone number endpoint
- [models/user.py](../../src/db/models/user.py) - Phone number storage
- [config.py](../../src/config.py) - WhatsApp configuration

**Frontend:**
- [settings/notifications.ts](../../web/src/components/settings/notifications.ts) - Phone number input
- [AgentEditor.ts](../../web/src/components/AgentEditor.ts) - Tool availability gating

**Migration:**
- [0026_add_whatsapp_phone.py](../../migrations/0026_add_whatsapp_phone.py) - User phone column

## Testing

- Unit tests: [test_whatsapp.py](../../tests/unit/test_whatsapp.py) - Tool, API client, formatting

## Troubleshooting

**"WhatsApp not configured" error:**
- Check all three env vars are set: `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_TEMPLATE_NAME`

**"Template name does not exist" error:**
- Template is still pending approval, or name doesn't match exactly

**"Recipient phone number is not in the allowed list" error:**
- For test numbers, add recipient to test recipients in Meta Developer Console

**Messages not delivered:**
- Verify phone number is registered on WhatsApp
- Check Meta Business Suite for delivery status
- Ensure access token hasn't expired

**"User has not configured their WhatsApp phone number" error:**
- User needs to add their phone number in Settings

## See Also

- [Integrations](integrations.md) - all integrations
- [Push Notifications](push-notifications.md) - the primary notification rail for autonomous agents
- [Autonomous Agents](agents.md) - agent configuration and scheduling
- [Setup](../setup.md) - WhatsApp Business setup
