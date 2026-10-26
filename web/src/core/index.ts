/**
 * Core module - main application logic.
 *
 * This module contains the core functionality split from main.ts into focused modules:
 * - init.ts: App startup order; startup/: per-feature startup (app shell,
 *   sign-in, initial data and route, sync start, composer, message UI, search)
 * - conversation.ts: Conversation selection, temp IDs, switching, New Chat
 *   (conversation-switch.ts: rendering a switch; conversation-actions.ts:
 *   delete/rename/pin/auto-title; archive.ts:
 *   archive view; conversation-deeplink.ts: URL routing;
 *   conversation-header.ts: chat header actions)
 * - messaging.ts: Message send entry point, steering, dispatch-level failures
 *   (stream-send.ts / batch-send.ts: the two send paths; stream-session/-events/
 *   -done/-resume.ts: the streaming engine; rerun.ts: regenerate/edit/retry;
 *   active-requests.ts: abort handles)
 * - planner.ts: Planner navigation and management
 * - search.ts: Search result handling and navigation
 * - tts.ts: Text-to-speech functionality
 * - toolbar.ts: Toolbar buttons initialization and state
 * - gestures.ts: Touch gestures and swipe handling
 * - file-actions.ts: File download, preview, clipboard operations
 * - events.ts: Event listeners and message handlers
 *
 * Import directly from the specific module you need, e.g.:
 *   import { sendMessage } from './core/messaging';
 *   import { selectConversation } from './core/conversation';
 */

// Re-export init for convenience
export { init } from './init';
