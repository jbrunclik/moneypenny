/**
 * Main entry point for the AI Chatbot frontend.
 *
 * This file has been refactored into focused modules in web/src/core/:
 * - init.ts: App initialization, login overlay, theme
 * - conversation.ts: Conversation CRUD, selection, temp IDs, switching
 * - messaging.ts: Message sending, streaming, batch mode, request management
 * - planner.ts: Planner navigation and management
 * - search.ts: Search result handling and navigation
 * - tts.ts: Text-to-speech functionality
 * - toolbar.ts: Toolbar buttons initialization and state
 * - gestures.ts: Touch gestures and swipe handling
 * - file-actions.ts: File download, preview, clipboard operations
 * - events.ts: Event listeners and message handlers
 * - sync-banner.ts: New messages available banner
 *
 * Import directly from the specific module you need, e.g.:
 *   import { sendMessage } from './core/messaging';
 *   import { selectConversation } from './core/conversation';
 */

import './styles/main.css';
import 'highlight.js/styles/github-dark.css';
// KaTeX CSS must load at the ENTRY point: imported from markdown.ts it lands
// in a code-split chunk's CSS, which the Flask template never injects
// (app.py injects only the main entry's css file from the Vite manifest)
import 'katex/dist/katex.min.css';

import { init } from './core/init';

// Start the app
document.addEventListener('DOMContentLoaded', init);
