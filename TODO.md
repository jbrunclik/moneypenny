# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] Conversation sharing (public links)
- [ ] Keyboard shortcuts
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output
- [ ] **Planner: Use temp conversation during loading** - Replace `'planner-loading'` placeholder with a real temp conversation ID (e.g., `temp-planner-${timestamp}`). This would allow users to send messages immediately while planner loads, leveraging the existing temp conversation persistence flow instead of blocking with a toast message.
- [ ] **Oura integration** - Allow planner to have access to health data
- [ ] **Conversation compaction for regular chats** - Implement conversation compaction when approaching model context limits (similar to `src/agent/compaction.py`)

## Autonomous Agents
- [ ] **Multi-step workflows** - Allow agents to run multi-step workflows
- [ ] **Lightweight database** - Provide agents with a lightweight database (k/v storage)

## Code Quality
- [ ] Consider async Flask (quart) for better concurrency
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.
