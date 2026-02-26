# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] **Conversation sharing** - Public links for sharing conversations
- [ ] **Keyboard shortcuts** - Add keyboard shortcuts for common actions
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output
- [ ] **Oura integration** - Allow planner to have access to health data
- [ ] **Conversation compaction for regular chats** - Implement conversation compaction when approaching model context limits (similar to `src/agent/compaction.py`). Prerequisite: windowed history loading (last N messages + summary) so chat endpoints stop reloading the entire history on every turn (O(n²) DB reads). Files: `chat.py`, `message.py`
- [ ] **Parallel tool execution** - Verify/ensure multi-tool calls execute in parallel through `create_tool_node()`, not sequentially
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls (e.g., same web search query within a conversation)

## Autonomous Agents
- [ ] **Multi-step workflows** - Allow agents to run multi-step workflows

## Planner Dashboard
- [ ] **Two-column layout** - Desktop two-column layout (events left, tasks right), task completion via Todoist API, open-in-Calendar links
- [ ] **Summary + timeline** - AI-generated daily summary strip, timeline view with hour markers, quick-add task from dashboard

## Security
- [ ] **Rate limiting: proxy-aware client IP** - Limiter uses `request.remote_addr` which collapses to the load-balancer IP behind a reverse proxy. Add `ProxyFix` middleware and switch limiter key to honor `X-Forwarded-For`. Files: `app.py`, `rate_limiting.py`
- [ ] **Logout: clear all sensitive state** - `store.logout()` only clears token/user/currentConversation, leaving messages, pagination, activeRequests in memory. Add `resetStore()` that wipes all maps/sets on `auth:logout`. Files: `store.ts`, `init.ts`

## Reliability
- [ ] **SyncManager.start() error handling** - Unhandled rejection silently disables background sync if `start()` throws. Await inside try/catch, log failures, allow retry. Files: `init.ts`, `SyncManager.ts`

## Code Quality
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.
