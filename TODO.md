# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] Text-to-speech tool
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output

### Code Quality
- [ ] Consider async Flask (quart) for better concurrency
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.
- [ ] **Search result navigation optimization** - Currently, when navigating to a search result in an old message, we load messages page-by-page from newest until we find the target message (up to 10 batches). A better approach would be to load the page containing the target message directly using a cursor based on the message's timestamp, then enable bi-directional pagination (older/newer) from that position.
