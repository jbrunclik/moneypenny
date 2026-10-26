# App Shell

Deep linking, the version update banner and the color scheme. Part of
[UI Features](ui-features.md).

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
| Open Trash (user menu) | `#/trash` | Added to history |

### Edge Cases Handled

1. **Temp conversation IDs in URL**: IDs starting with `temp-` are ignored and hash is cleared
2. **Deleted conversations**: If deep-linked conversation doesn't exist, shows error toast and clears hash
3. **Conversations not in paginated list**: Fetches conversation from API if not found in local store
4. **Malformed hashes**: Invalid routes are ignored (app shows home view)

### Key Files

**Router module:**
- [deeplink.ts](../../web/src/router/deeplink.ts) - Router functions

**Integration:**
- [init.ts](../../web/src/core/init.ts) - Deep linking initialization; [startup/initial-route.ts](../../web/src/core/startup/initial-route.ts) - opening the initial route after sign-in
- [conversation-deeplink.ts](../../web/src/core/conversation-deeplink.ts) - Deep linking handlers and navigation
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
- [settings/appearance.ts](../../web/src/components/settings/appearance.ts) - Color scheme selector UI
- [variables.css](../../web/src/styles/variables.css) - CSS custom properties for both themes
- [icons.ts](../../web/src/utils/icons.ts) - `SUN_ICON`, `MOON_ICON`, `MONITOR_ICON` for theme options
- [init.ts](../../web/src/core/init.ts) - Early theme initialization to prevent flash of wrong theme

### Testing

- E2E tests: Color Scheme describe block in [settings.spec.ts](../../web/tests/e2e/settings.spec.ts)
- Visual tests: All visual test snapshots capture the dark theme (default)
