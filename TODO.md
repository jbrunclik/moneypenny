# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **URL detection and clickability** - Automatically detect URLs in messages (from both user and assistant) and convert them to clickable links. Should handle common URL patterns (http://, https://, www.) and preserve markdown link syntax.
- [ ] **Weather context for planner** - Fetch weather information from Yr.no and include it in the planner dashboard context for location-aware planning suggestions
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output
- [ ] **Planner: Use temp conversation during loading** - Replace `'planner-loading'` placeholder with a real temp conversation ID (e.g., `temp-planner-${timestamp}`). This would allow users to send messages immediately while planner loads, leveraging the existing temp conversation persistence flow instead of blocking with a toast message.
- [ ] **Planner: Dashboard refresh tool for LLM** - Add a `refresh_planner_dashboard` tool that the LLM can call after updating tasks (via todoist tool) or calendar events (via google_calendar tool) in planner mode. This would fetch fresh dashboard data and update the system prompt context mid-conversation, ensuring the LLM has accurate information about the current state of tasks and events without requiring manual user refresh.

## Code Quality
- [ ] **Split tools.py into separate modules** - The `src/agent/tools.py` file is over 2800 lines and growing. Split into separate modules per integration: `tools/todoist.py`, `tools/google_calendar.py`, `tools/web_search.py`, `tools/code_execution.py`, `tools/image_generation.py`, `tools/file_retrieval.py`. Keep a central `tools/__init__.py` that exports the combined `TOOLS` list.
- [ ] **Refactor MIME type logic** - Replace manual `_get_mime_type` and maps in `src/agent/tools.py` with Python's standard `mimetypes` library.
- [ ] Consider async Flask (quart) for better concurrency
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.
- [ ] **Frontend Race Conditions** - Fix `currentStreamingContext` in `Messages.ts`. It's currently overwritten without cleaning up the previous listener, potentially leaving "zombie" listeners.
- [ ] **Brittle Scroll Detection** - `setupStreamingScrollListener` relies on `scrollTop < previousScrollTop` to detect user intervention. This causes false pauses when images load above the viewport. Move to `wheel`/`touchmove` event detection.
- [ ] **Sandbox Performance** - Stop running `apt-get install fonts-dejavu-core` inside the 30s runtime timeout. Move this to a custom Dockerfile with pre-installed fonts.
