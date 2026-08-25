# Setup Guides

Operator-facing walkthroughs for the optional capabilities and integrations.
Each one is independent - skip what you don't need, the app degrades gracefully.

## Setting up Code Execution (Docker)

The code execution feature allows the AI to run Python code in a secure, isolated Docker container. This is optional but enables powerful capabilities like data analysis, chart generation, and PDF creation.

**Prerequisites:**
- Docker installed and running
- User must have access to the Docker socket

**Build the custom sandbox image:**

```bash
make sandbox-image
```

This creates `ai-chatbot-sandbox:local` with pre-installed fonts and Python libraries for faster execution.

**Local Development (macOS/Linux):**
```bash
# Docker Desktop on macOS/Windows handles permissions automatically
# On Linux, add your user to the docker group:
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect
```

**Production Server (Linux with systemd):**

If running the app as a systemd service, the service user needs Docker socket access:

```bash
# 1. Add the service user to the docker group
sudo usermod -aG docker $USER

# 2. If using socket activation, ensure the socket is accessible
# Check socket permissions:
ls -la /var/run/docker.sock
# Should show: srw-rw---- 1 root docker ...

# 3. If still having issues, you may need to restart the Docker service:
sudo systemctl restart docker

# 4. Restart your application service:
systemctl --user restart ai-chatbot
```

**Disabling Code Execution:**

If you don't want to set up Docker, simply disable the feature:
```bash
CODE_SANDBOX_ENABLED=false
```

The AI will gracefully handle this and won't offer code execution capabilities.

**Security Notes:**
- Code runs in isolated containers with no network access
- Containers have memory and CPU limits
- Files are only accessible within the sandbox (`/output/` directory)
- Each execution creates a fresh container that is destroyed after use

## Setting up Browser Automation

The browser tool gives the AI a full headless Chromium browser. Unlike simple URL fetching, it renders JavaScript, maintains session state (cookies, history) across turns, and can click buttons, fill forms, and take screenshots. Useful for SPAs, paywalled previews, and any page that requires interaction.

**Prerequisites:**
- Python `playwright` package and Chromium browser binary

**Install:**

```bash
make browser-setup
```

This runs `pip install playwright` and `playwright install chromium --with-deps` inside the virtual environment.

**Configuration (`.env`):**
```bash
BROWSER_ENABLED=true                 # Enable/disable (default: true)
BROWSER_SESSION_TTL_SECONDS=600      # Idle session cleanup (default: 600 s)
BROWSER_MAX_CONCURRENT_SESSIONS=5    # Max simultaneous sessions (default: 5)
BROWSER_PAGE_TIMEOUT_MS=30000        # Per-action timeout (default: 30 000 ms)
```

**Disabling:**

Set `BROWSER_ENABLED=false` to disable the tool. The AI will fall back to `fetch_url` for web content. If Playwright is not installed, the tool returns a graceful error rather than crashing.

**Security:**
- All URLs are validated against an SSRF blocklist (private IP ranges, loopback, link-local) before navigation
- The browser never stores or enters passwords

## Setting up Todoist Integration

The Todoist integration allows the AI to manage your tasks - list, add, complete, prioritize, and organize tasks across projects. Each user connects their own Todoist account via OAuth.

**Prerequisites:**
- A Todoist account
- A registered Todoist OAuth app

**Setup:**

1. Go to [Todoist App Console](https://developer.todoist.com/appconsole.html)
2. Click **Create a new app**
3. Fill in the app details:
   - **App name**: Your chatbot name
   - **App service URL**: Your deployment URL (e.g., `https://yourdomain.com`)
   - **OAuth redirect URL**: Your deployment URL (e.g., `https://yourdomain.com` for production, `http://localhost:5173` for development with Vite)
4. Copy the **Client ID** and **Client Secret** to your `.env` file

**Configuration:**
```bash
TODOIST_CLIENT_ID=your-client-id
TODOIST_CLIENT_SECRET=your-client-secret
TODOIST_REDIRECT_URI=http://localhost:5173  # Your app URL (use Vite port in dev)
```

**Usage:**
1. Open Settings (gear icon in sidebar)
2. Click "Connect Todoist" in the Todoist Integration section
3. Authorize the app on Todoist's OAuth page
4. Once connected, ask the AI to help manage your tasks:
   - "Show me my tasks for today"
   - "What's overdue?"
   - "Add a task to buy groceries"
   - "Mark the first task as complete"
   - "Prioritize my work project tasks"

**Disabling Todoist:**

Simply leave `TODOIST_CLIENT_ID` empty - the integration won't appear in settings and the AI won't offer task management capabilities.

## Setting up Google Sign In

To enable authentication (required for production):

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project (or select an existing one)
3. Configure the **OAuth consent screen**:
   - Go to **APIs & Services** → **OAuth consent screen**
   - Select **External** (or Internal for Google Workspace)
   - Fill in required fields (app name, support email)
   - Add your email(s) as test users (required while in "Testing" status)
   - To move from "Testing" to "Production", add your app's `/privacy` URL as the privacy policy link — the app serves this page at `https://yourdomain.com/privacy`
4. Create **OAuth credentials**:
   - Click **Create Credentials** → **OAuth client ID**
   - Select **Web application** as the application type
   - Add **Authorized JavaScript origins**:
     - `http://localhost:5173` (for development with Vite)
     - `https://yourdomain.com` (for production)
   - Copy the **Client ID** to your `.env` file

No client secret is needed - the app uses Google Identity Services which validates tokens server-side.

## Setting up Google Calendar Integration

The Google Calendar integration allows the AI to schedule meetings, create focus blocks, update events, and RSVP to invitations. Each user connects their own Google Calendar account via OAuth.

**Cost:** Google Calendar API is **free** for personal use with generous quotas (1,000,000 queries/day).

**Setup:**

1. Use the same Google Cloud project as your Sign-In client (or create a new one)
2. Enable the **Google Calendar API**:
   - Go to **APIs & Services** → **Library**
   - Search for "Google Calendar API"
   - Click **Enable**
3. Create a **separate OAuth client** for Calendar:
   - Go to **APIs & Services** → **Credentials**
   - Click **Create Credentials** → **OAuth client ID**
   - Select **Web application**
   - Add **Authorized redirect URIs** (not JavaScript origins):
     - `http://localhost:5173` (for development with Vite)
     - `https://yourdomain.com` (for production)
   - Copy the **Client ID** and **Client Secret**

**Why a separate OAuth client?** The Sign-In client uses Google Identity Services (no secret needed), while Calendar uses standard OAuth with a secret. Separate clients let users use the chatbot without granting calendar access.

**Configuration:**
```bash
GOOGLE_CALENDAR_CLIENT_ID=your-calendar-client-id
GOOGLE_CALENDAR_CLIENT_SECRET=your-calendar-client-secret
GOOGLE_CALENDAR_REDIRECT_URI=http://localhost:5173  # Use Vite port in dev
```

**Usage:**
1. Open Settings (gear icon in sidebar)
2. Click "Connect Google Calendar"
3. Authorize on Google's OAuth page
4. Select which calendars to include in the planner (work, personal, shared calendars)
   - Primary calendar is always included
   - Events from multiple calendars are combined in the planner dashboard
   - Calendar labels help distinguish events from different calendars
5. Ask the AI to manage your calendar:
   - "What's on my calendar today?"
   - "Schedule a meeting with John tomorrow at 2pm"
   - "Block 2 hours for deep work on Monday morning"
   - "Cancel my 3pm meeting"

**Disabling:** Leave `GOOGLE_CALENDAR_CLIENT_ID` empty - the integration won't appear.

## Setting up Garmin Connect Integration

The Garmin Connect integration allows the AI to query your health and fitness data — steps, sleep, heart rate, HRV, SpO2, body composition, training readiness, and activities. It is read-only; no data is written to Garmin.

**Prerequisites:**
- A Garmin Connect account

**No app registration required** — users authenticate with their own Garmin email and password. The password is never stored; only session tokens (valid ~1 year) are persisted.

**MFA support:** If your Garmin account has two-factor authentication enabled, you will be prompted for a verification code after entering your credentials.

**Configuration:**
```bash
GARMIN_API_TIMEOUT=15  # Optional, default is 15 seconds
```

**Usage:**
1. Open Settings (gear icon in sidebar)
2. Click "Connect Garmin" and enter your Garmin Connect email and password
3. If MFA is enabled, enter the verification code from your email or authenticator app
4. Once connected, ask the AI about your fitness data:
   - "How did I sleep last night?"
   - "What's my training readiness today?"
   - "Show me my last 5 runs"
   - "What was my resting heart rate this week?"

**Disabling:** If you do not want Garmin Connect to appear, it is available whenever the `garminconnect` Python package is installed (included in `requirements.txt`). Users who do not connect their account simply won't have the tool available.

## Setting up WhatsApp Integration (Autonomous Agents)

The WhatsApp integration allows autonomous agents to send execution results and notifications to your phone via WhatsApp. This uses Meta's official WhatsApp Cloud API.

**Cost:** WhatsApp Cloud API offers **1,000 free conversations/month**. Beyond that, costs are ~$0.005-0.05 per conversation depending on region.

**Prerequisites:**
- A Meta (Facebook) account
- A phone number to receive messages (can be your personal WhatsApp number)

**Key Concepts:**

Before setting up, understand these important WhatsApp Business API concepts:

- **Phone Number ID**: A numeric ID (e.g., `982966681562240`), NOT the phone number itself. This is a common mistake!
- **Phone Registration**: Your business phone must be registered via the API before it can send messages
- **24-Hour Window**: You can only send free-form text messages within 24 hours after a user messages you first
- **Template Messages**: For business-initiated conversations (first contact), you MUST use pre-approved message templates
- **Test vs Production**: The `hello_world` template only works with test phone numbers, not production

**Setup:**

1. **Create a Meta Business Account** (if you don't have one):
   - Go to [Meta Business Suite](https://business.facebook.com/)
   - Click "Create Account" and follow the prompts

2. **Create a WhatsApp Business App**:
   - Go to [Meta for Developers](https://developers.facebook.com/)
   - Click "My Apps" → "Create App"
   - Select "Business" as the app type
   - Fill in app details and click "Create App"

3. **Add WhatsApp to your app**:
   - In your app dashboard, click "Add Product"
   - Find "WhatsApp" and click "Set Up"

4. **Add your business phone number**:
   - Go to **WhatsApp** → **API Setup**
   - Click "Add phone number" and follow the verification process
   - You may need to download a certificate to verify ownership
   - Once verified, note the **Phone number ID** (a numeric ID like `982966681562240`)

5. **Register your phone number** (required before sending):
   ```bash
   curl -X POST "https://graph.facebook.com/v18.0/YOUR_PHONE_NUMBER_ID/register" \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"messaging_product": "whatsapp", "pin": "123456"}'
   ```
   You should see `{"success": true}`.

6. **Generate a permanent access token**:
   - Go to **Business Settings** → **System Users**
   - Create a System User with "Admin" role
   - Click "Generate Token" → Select your WhatsApp app
   - Add permissions: `whatsapp_business_messaging`, `whatsapp_business_management`
   - Copy the permanent token to your `.env` file

7. **Create a message template** (required for business-initiated messages):
   - Go to [Meta Business Suite](https://business.facebook.com/) → **WhatsApp Manager** → **Message Templates**
   - Create a new template (e.g., name: `agent_notification`, category: `UTILITY`)
   - Use a body with two variables: `{{1}}: {{2}}`
     - `{{1}}` = Agent name (e.g., "Daily Briefing Agent")
     - `{{2}}` = Message content
   - Submit for review (usually approved within minutes for utility templates)
   - Note the template name for your `.env` file

8. **Enable billing** (for production):
   - Go to **WhatsApp** → **API Setup** → **Payment settings**
   - Add a payment method to enable production messaging
   - Without billing, you can only message numbers added to your test recipient list

**Configuration:**
```bash
# WhatsApp Cloud API credentials (app-level)
# IMPORTANT: Phone Number ID is a numeric ID, NOT the phone number!
WHATSAPP_PHONE_NUMBER_ID=982966681562240          # From API Setup page (numeric ID)
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxx...               # Permanent token from System User
WHATSAPP_TEMPLATE_NAME=agent_notification         # Your approved template name
```

**User Setup:**

Each user needs to configure their WhatsApp phone number in the app settings (Settings → WhatsApp). The phone number must be:
- In E.164 format (e.g., `+1234567890`)
- A valid WhatsApp account

**Usage:**

WhatsApp messaging is available as an agent tool. To enable it for an autonomous agent:

1. Add `whatsapp` to the agent's tool permissions
2. Include instructions in the agent's system prompt to send WhatsApp notifications, e.g.:
   - "After completing your analysis, send the results via WhatsApp"
   - "Notify me via WhatsApp when the task is done"

The agent will only send WhatsApp messages when explicitly instructed in its goals.

**Testing the setup:**

For testing within the 24-hour window (after user messages you):
```bash
curl -X POST "https://graph.facebook.com/v18.0/$WHATSAPP_PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "1234567890",
    "type": "text",
    "text": {"body": "Hello from Moneypenny!"}
  }'
```

For business-initiated messages (using template with two parameters):
```bash
curl -X POST "https://graph.facebook.com/v18.0/$WHATSAPP_PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "1234567890",
    "type": "template",
    "template": {
      "name": "agent_notification",
      "language": {"code": "en"},
      "components": [{"type": "body", "parameters": [{"type": "text", "text": "Test Agent"}, {"type": "text", "text": "Your task is complete!"}]}]
    }
  }'
```

**Troubleshooting:**

| Error | Cause | Solution |
|-------|-------|----------|
| `133010 Account not registered` | Business phone not registered | Run the `/register` endpoint (step 5) |
| `131030 Recipient not in allowed list` | Test mode limitation | Add recipient to test list or enable billing |
| `131058 Hello World templates can only be sent from Public Test Numbers` | Using hello_world in production | Create your own message template |
| `100 messaging_product is required` | Malformed request | Check JSON structure and Content-Type header |

**Limitations:**
- Template messages required for first contact (outside 24-hour window)
- Templates must be pre-approved by Meta (usually quick for utility category)
- Messages have a 4096 character limit (longer content is automatically truncated)
- Rate limits apply based on your messaging tier (starts at 250 messages/day)

**Disabling:** Leave `WHATSAPP_PHONE_NUMBER_ID` empty - the integration won't be available.
