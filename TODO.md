# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] Text-to-speech tool
- [ ] Conversation export (JSON, Markdown)
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output
- [ ] **LLM file/image retrieval tool** - Add tool for LLM to explicitly fetch any previous file/image from conversation history by message ID and file index. Enables referencing past uploads for context or passing to `generate_image` as reference images without user re-uploading.

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

### Database
- [ ] **Add database connection pooling** - Each operation creates a new connection. Consider pooling for better performance under load

### Frontend Performance & UX
- [ ] **Add service worker** - Implement service worker for offline support and better caching
- [ ] **Add file upload progress** - Show upload progress indicator for large file uploads
- [ ] **Frontend code splitting** - Split frontend code into chunks for better initial load performance
- [ ] **Frontend error reporting** - Add error reporting service (Sentry, Rollbar) for production error tracking
- [ ] **Frontend bundle analysis** - Analyze bundle size and identify optimization opportunities
- [ ] **Blob URL memory leak in thumbnails** - In `thumbnails.ts`, blob URLs created with `URL.createObjectURL()` rely on MutationObserver to detect DOM removal for cleanup. If parent element is removed directly or observer doesn't fire (e.g., rapid conversation switches), blob URLs leak. **Fix**: Track all created blob URLs in a Set keyed by message ID. Add cleanup function called on conversation switch that revokes all URLs for that conversation's messages.
- [ ] **Multiple scroll listeners possible** - In `thumbnails.ts`, `enableScrollOnImageLoad()` can be called multiple times without cleanup if conversation switching is rapid. Each call adds a new scroll listener via `setupUserScrollListener()`. While `removeUserScrollListener()` is called first, rapid calls could race. **Fix**: Use a debounced enable function or add a guard to prevent re-enabling within a short window.
- [ ] **Streaming context state inconsistency** - In `main.ts`, `streamingMessageElements` Map and `currentStreamingContext` in `Messages.ts` can become inconsistent if user rapidly switches conversations during streaming. Both track streaming state but are not synchronized atomically. **Fix**: Consolidate streaming state into a single source of truth, or add explicit synchronization between the two.
