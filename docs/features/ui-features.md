# UI Features

This document covers user-facing UI features including the input toolbar, conversation management, deep linking, version updates, and color scheme.

## Input Toolbar

The input area has a toolbar row above the textarea with controls:

```
[Model dropdown] [Stream] [Search]              [Mic] [Attach] [Anonymous]
┌────────────────────────────────────────────────────────────┐
│ Textarea                                          [Send]   │
└────────────────────────────────────────────────────────────┘
```

- **Model selector**: Dropdown to switch between Gemini models
- **Stream toggle**: Enable/disable streaming responses (persisted to localStorage)
- **Search toggle**: One-shot button to force `web_search` tool for the next message only
- **Mic**: Voice input (see [Voice and TTS](voice-and-tts.md))
- **Attach**: File upload (see [File Handling](file-handling.md))
- **Anonymous**: Anonymous mode toggle (see [Anonymous Mode](memory-and-context.md#anonymous-mode))

## Message Sending Behavior

The Enter key behavior differs between desktop and mobile viewports:

- **Desktop** (viewport > 768px): Enter sends the message, Shift+Enter adds a newline
- **Mobile** (viewport ≤ 768px): Enter always adds a newline, users must tap the Send button

This allows mobile users to easily add multiple lines to their prompts (since there's no easy way to type Shift+Enter on mobile keyboards), while preserving the convenient Enter-to-send behavior on desktop.

**Implementation:**
- `isMobileViewport()` in [MessageInput.ts](../../web/src/components/MessageInput.ts) checks `window.innerWidth` against `MOBILE_BREAKPOINT_PX`
- The keydown handler only sends on Enter when NOT in mobile viewport
- `MOBILE_BREAKPOINT_PX` (768px) is defined in [config.ts](../../web/src/config.ts) and matches the CSS media query breakpoint in [layout.css](../../web/src/styles/layout.css)

## Force Tools System

The `forceTools` state in Zustand allows forcing specific tools to be used. Currently only `web_search` is exposed via UI, but the system supports any tool name. The force tools instruction is added to the system prompt when tools are specified.

- **Frontend**: `store.forceTools: string[]` with `toggleForceTool(tool)` and `clearForceTools()`
- **Backend**: `force_tools` parameter in `/chat/batch` and `/chat/stream` endpoints
- **Agent**: `get_force_tools_prompt()` in [prompts.py](../../src/agent/prompts.py)

## Clipboard Paste

Users can paste screenshots directly from the clipboard into the message input (Cmd+V / Ctrl+V).

### How It Works

1. A `paste` event listener on the textarea detects clipboard content
2. If clipboard contains image files, they're extracted and processed
3. Images are renamed with timestamp-based names (`screenshot-YYYY-MM-DDTHH-MM-SS.png`)
4. Uses the existing `addFilesToPending()` flow for validation and preview
5. Text paste is handled normally by the browser (not intercepted)

### Supported Formats

- PNG, JPEG, GIF, WebP images
- Works with screenshots (Cmd+Shift+4 on Mac, PrtScn on Windows)
- Works with copied images from other applications

### Key Files

- [MessageInput.ts](../../web/src/components/MessageInput.ts) - `handlePaste()` function
- [FileUpload.ts](../../web/src/components/FileUpload.ts) - `addFilesToPending()` for file processing

### Testing

- Unit tests: `handlePaste` describe block in [message-input.test.ts](../../web/tests/unit/message-input.test.ts)
- E2E tests: "Chat - Clipboard Paste" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)

## URL Detection and Link Handling

The app automatically detects URLs in messages and converts them to clickable links. All links (both auto-detected and markdown links from LLM responses) open in new tabs with security attributes.

### Auto-Linkification

**User messages** are scanned for URLs and automatically converted to clickable links.

**Supported patterns:**
- `http://` and `https://` URLs
- `www.` prefixed URLs (automatically prepended with `https://`)

**Example:**
```
User types: "Check out https://example.com and www.test.org"
Result: Both URLs become clickable links
```

### Link Security

All links include security attributes:
- `target="_blank"` - Opens in new tab
- `rel="noopener noreferrer"` - Prevents security vulnerabilities:
  - `noopener` - New tab can't access `window.opener` (prevents tabnabbing)
  - `noreferrer` - Doesn't send referrer header (privacy)

### Implementation

**User messages:**
- Plain text URLs are detected using regex pattern in [linkify.ts](../../web/src/utils/linkify.ts)
- `linkifyText()` converts URLs to anchor tags after HTML escaping
- Applied in [Messages.ts](../../web/src/components/Messages.ts) when rendering user messages

**Assistant messages:**
- Markdown links are rendered by the `marked` library
- Custom link renderer in [markdown.ts](../../web/src/utils/markdown.ts) adds security attributes
- Works for all markdown link formats: `[text](url)`, `<url>`, etc.

### Key Files

- [linkify.ts](../../web/src/utils/linkify.ts) - URL detection and auto-linking utility
- [markdown.ts](../../web/src/utils/markdown.ts) - Custom link renderer for markdown
- [Messages.ts](../../web/src/components/Messages.ts) - Integration into message rendering

### Testing

- Unit tests: [linkify.test.ts](../../web/tests/unit/linkify.test.ts) - URL detection patterns, edge cases
- E2E tests: [links.spec.ts](../../web/tests/e2e/links.spec.ts) - Link behavior in user and assistant messages, security attributes

---

## Copy to Clipboard

The app provides copy-to-clipboard functionality at two levels:

### 1. Message-Level Copy

Copy button in message actions copies the entire message content.

**Behavior:**
- Excludes file attachments, thinking/tool traces, inline copy buttons, and language labels
- Available on both user and assistant messages
- Shows checkmark feedback for 2 seconds after successful copy

### 2. Inline Copy

Individual copy buttons on code blocks and tables.

**Appearance:**
- Appear on hover (desktop) or always visible at 70% opacity (touch devices)
- Code blocks: Shows language label (e.g., "python") in top-left corner
- Tables: Wrapped in a bordered container for visual distinction
- Copy button positioned in top-right corner of each block

### Rich Text Support

- Copies both HTML and plain text formats using the Clipboard API
- When pasted into rich text editors (Word, Google Docs, etc.), formatting is preserved
- Tables are copied as HTML tables (preserves structure when pasted)
- Code blocks are copied as plain text (no syntax highlighting in clipboard)
- Plain text fallback for applications that don't support rich text

### Key Files

- [markdown.ts](../../web/src/utils/markdown.ts) - Custom renderers for code blocks and tables with copy button injection
- [file-actions.ts](../../web/src/core/file-actions.ts) - `copyMessageContent()`, `copyInlineContent()`, `copyWithRichText()`
- [messages.css](../../web/src/styles/components/messages.css) - `.copyable-content`, `.inline-copy-btn`, `.code-language` styles

### Testing

- E2E tests: "Chat - Copy to Clipboard" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)

---

## Conversation Management

The sidebar displays a list of conversations with hover actions for rename and delete.

### Rename

- **Desktop**: Hover over a conversation to reveal action buttons, click the pencil icon to rename
- **Mobile**: Swipe left on a conversation to reveal rename and delete buttons
- Opens a prompt modal with the current title pre-filled
- Updates both the sidebar title and the chat header title (if viewing that conversation)
- Shows a success toast on completion
- Empty names are rejected (modal closes without changes)

### Delete

- **Desktop**: Hover over a conversation to reveal action buttons, click the trash icon to delete
- **Mobile**: Swipe left on a conversation to reveal delete button
- Shows a confirmation modal before deleting
- Cost data is intentionally preserved after deletion for accurate reporting

### Key Files

- [Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversation list rendering, rename/delete handlers
- [conversation.ts](../../web/src/core/conversation.ts) - `renameConversation()` function
- [Modal.ts](../../web/src/components/Modal.ts) - `showPrompt()` and `showConfirm()` dialogs

---

## Deep Linking

The app supports hash-based routing (`#/conversations/{conversationId}`) for deep linking to specific conversations.

### Features

- **Bookmarkable URLs**: Each conversation has a unique URL that can be bookmarked or shared
- **Browser history**: Back/forward navigation works between conversations
- **Page refresh**: Reloading the page returns to the same conversation
- **Initial route handling**: Deep links are processed before sync manager starts to prevent false "new messages" banners

### How It Works

1. **Hash format**: `#/conversations/{conversationId}` (e.g., `#/conversations/abc-123-def`)
2. **Route parsing**: `parseHash()` extracts conversation ID from URL hash
3. **Initial load**: `initDeepLinking()` returns the initial conversation ID for `loadInitialData()` to handle
4. **Hash updates**: `setConversationHash()` updates URL when switching conversations
5. **Browser navigation**: `hashchange` event listener handles back/forward navigation

### URL Update Behavior

| Action | Hash behavior | History |
|--------|---------------|---------|
| Click conversation in sidebar | `pushState(#/conversations/{id})` | Added to history |
| Click "New Chat" | `pushState("")` - clears hash | Added to history |
| Temp conversation persisted | `replaceState(#/conversations/{id})` | Replaces empty hash |
| Conversation deleted | `replaceState("")` - clears hash | No new entry |

### Edge Cases Handled

1. **Temp conversation IDs in URL**: IDs starting with `temp-` are ignored and hash is cleared
2. **Deleted conversations**: If deep-linked conversation doesn't exist, shows error toast and clears hash
3. **Conversations not in paginated list**: Fetches conversation from API if not found in local store
4. **Malformed hashes**: Invalid routes are ignored (app shows home view)

### Key Files

**Router module:**
- [deeplink.ts](../../web/src/router/deeplink.ts) - Router functions

**Integration:**
- [init.ts](../../web/src/core/init.ts) - Deep linking initialization
- [conversation.ts](../../web/src/core/conversation.ts) - Deep linking handlers and navigation
- [store.ts](../../web/src/state/store.ts) - `currentConversationId` persisted to localStorage

### Testing

- Unit tests: [deeplink.test.ts](../../web/tests/unit/deeplink.test.ts) - Router function tests
- E2E tests: [deeplink.spec.ts](../../web/tests/e2e/deeplink.spec.ts) - Full deep linking scenarios including browser navigation, edge cases, and pagination

---

## Version Update Banner

The app detects when a new version is deployed and shows a banner prompting users to reload.

### How It Works

1. **Version source**: The Vite JS bundle hash (e.g., `main-y-VVsbiY.js` → `y-VVsbiY`) serves as the version identifier
2. **Initial load**: Flask extracts the version from the Vite manifest and injects it into the HTML via `data-version` attribute on `#app`
3. **Periodic polling**: Frontend polls `GET /api/version` every 5 minutes (no auth required)
4. **PWA awareness**: Polling pauses when tab is hidden (`document.visibilitychange`), checks immediately on refocus if >5 min since last check
5. **Dismiss persistence**: Dismissed versions are stored in localStorage to avoid re-showing the same banner

### Key Files

- [app.py](../../src/app.py) - Extracts version hash from manifest, stores in `app.config["APP_VERSION"]`
- [routes/system.py](../../src/api/routes/system.py) - `GET /api/version` endpoint
- [VersionBanner.ts](../../web/src/components/VersionBanner.ts) - Banner component and polling logic
- [store.ts](../../web/src/state/store.ts) - Version state management

### Testing Locally

In development mode, the version will be `null` (no manifest). Use the test helper in browser console:
```javascript
window.__testVersionBanner()
```

---

## Color Scheme

The app supports three color scheme options: Light, Dark, and System (default).

### How It Works

1. **Storage**: Theme preference is stored in localStorage under `ai-chatbot-color-scheme`
2. **UI**: Color scheme selector in the settings popup with three options (Light, Dark, System)
3. **Application**: Theme is applied via `data-theme="light"` attribute on the `<html>` element
4. **Immediate effect**: Theme changes are applied instantly without requiring a save
5. **System preference**: When "System" is selected, the app follows the OS preference and updates automatically when it changes

### Theme Implementation

**CSS variables approach:**
- Base theme (dark) is defined in `:root` in [variables.css](../../web/src/styles/variables.css)
- Light theme overrides are defined in `[data-theme="light"]` selector
- Uses semantic color aliases (`--bg-primary`, `--text-primary`, `--accent`, etc.) that map to the current theme

**Key color variables:**
- `--bg-primary`, `--bg-secondary`, `--bg-tertiary` - Background colors
- `--text-primary`, `--text-secondary`, `--text-muted` - Text colors
- `--border`, `--border-light` - Border colors
- `--accent`, `--accent-hover`, `--accent-muted` - Accent/brand colors
- `--color-user-text` - Text color for user messages (white, for contrast on blue background)

### Key Files

- [theme.ts](../../web/src/utils/theme.ts) - Theme utility functions
- [SettingsPopup.ts](../../web/src/components/SettingsPopup.ts) - Color scheme selector UI
- [variables.css](../../web/src/styles/variables.css) - CSS custom properties for both themes
- [icons.ts](../../web/src/utils/icons.ts) - `SUN_ICON`, `MOON_ICON`, `MONITOR_ICON` for theme options
- [init.ts](../../web/src/core/init.ts) - Early theme initialization to prevent flash of wrong theme

### Testing

- E2E tests: Color Scheme describe block in [settings.spec.ts](../../web/tests/e2e/settings.spec.ts)
- Visual tests: All visual test snapshots capture the dark theme (default)

## See Also

- [Mobile and PWA](../ui/mobile-and-pwa.md) - Touch gestures for conversation swipe actions
- [File Handling](file-handling.md) - File upload and preview
- [Voice and TTS](voice-and-tts.md) - Voice input button
- [Search](search.md) - Search input in sidebar
- [Sync](sync.md) - Unread badges in conversation list
