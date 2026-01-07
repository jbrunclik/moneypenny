# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] Text-to-speech tool
- [ ] Conversation export (JSON, Markdown)
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output

## Technical Debt

### Connection Resilience (Slow/Unreliable Networks)
- [ ] **Detect and handle offline state** - Show offline indicator when network is unavailable. Queue messages locally and sync when connection returns.
- [ ] **Handle partial file uploads** - Large file uploads can fail mid-transfer. Consider chunked uploads with resume capability, or at minimum show clear error and allow retry.
- [ ] **Add connection quality indicator** - Show visual feedback when connection is slow (e.g., SSE keepalives arriving but no tokens for extended period).

### Security
- [ ] **Add request size limits** - Enforce request body size limits in Flask to prevent DoS. Set `app.config['MAX_CONTENT_LENGTH']`
- [ ] **Add rate limiting** - Add Flask-Limiter or similar to prevent abuse/DoS

### Code Quality
- [ ] Consider async Flask (quart) for better concurrency
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing (100ms, 150ms, RAF). **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.

### Frontend Performance & UX
- [ ] **Add service worker** - Implement service worker for offline support and better caching
- [ ] **Add file upload progress** - Show upload progress indicator for large file uploads
- [ ] **Frontend code splitting** - Split frontend code into chunks for better initial load performance
- [ ] **Frontend error reporting** - Add error reporting service (Sentry, Rollbar) for production error tracking
- [ ] **Frontend bundle analysis** - Analyze bundle size and identify optimization opportunities
