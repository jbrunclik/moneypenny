# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output

## Code Quality
- [ ] **Refactor MIME type logic** - Replace manual `_get_mime_type` and maps in `src/agent/tools.py` with Python's standard `mimetypes` library.
- [ ] Consider async Flask (quart) for better concurrency
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.
- [ ] **Frontend Race Conditions** - Fix `currentStreamingContext` in `Messages.ts`. It's currently overwritten without cleaning up the previous listener, potentially leaving "zombie" listeners.
- [ ] **Brittle Scroll Detection** - `setupStreamingScrollListener` relies on `scrollTop < previousScrollTop` to detect user intervention. This causes false pauses when images load above the viewport. Move to `wheel`/`touchmove` event detection.
- [ ] **Sandbox Performance** - Stop running `apt-get install fonts-dejavu-core` inside the 30s runtime timeout. Move this to a custom Dockerfile with pre-installed fonts.
