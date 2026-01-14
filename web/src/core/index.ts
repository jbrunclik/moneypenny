/**
 * Core module - main application logic.
 *
 * This module contains the core functionality split from main.ts into focused modules:
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

// Re-export init for convenience
export { init } from './init';
