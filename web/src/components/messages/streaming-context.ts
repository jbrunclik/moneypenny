/**
 * The reply streaming on screen: its element, thinking state and follow
 * flag, shared by the streaming modules.
 */
import { setStreamingPausedIndicator } from '../ScrollToBottom';
import type { StreamingMessageContext } from './types';

// Global context for the current streaming message
let currentStreamingContext: StreamingMessageContext | null = null;

/** The context of the reply streaming on screen, if any. */
export function getStreamingContext(): StreamingMessageContext | null {
  return currentStreamingContext;
}

/** Make `context` the streaming reply's context (null: none). */
export function setStreamingContext(context: StreamingMessageContext | null): void {
  currentStreamingContext = context;
}

/**
 * Clean up streaming context and scroll listener.
 * Called when streaming ends (success or error).
 */
export function cleanupStreamingContext(conversationId?: string): void {
  // A turn ending in another conversation (a background stream finishing)
  // must not tear down the live reply on screen: its thinking, tool and
  // autoscroll updates all go through this context
  if (conversationId !== undefined && currentStreamingContext && currentStreamingContext.conversationId !== conversationId) {
    return;
  }
  if (currentStreamingContext) {
    if (currentStreamingContext.scrollListenerCleanup) {
      currentStreamingContext.scrollListenerCleanup();
    }
    currentStreamingContext = null;
  }
  // Always clear the streaming paused indicator when streaming ends
  setStreamingPausedIndicator(false);
}

/**
 * Check if there is an active streaming context
 */
export function hasActiveStreamingContext(): boolean {
  return currentStreamingContext !== null;
}

/**
 * Get the conversation ID of the current streaming context, if any.
 * Used to determine if we should clean up the context when switching conversations.
 */
export function getStreamingContextConversationId(): string | null {
  return currentStreamingContext?.conversationId ?? null;
}

/**
 * Get the current streaming message element, if any.
 * This is the single source of truth for the streaming element.
 * @param conversationId - Optional: only return element if it matches this conversation
 */
export function getStreamingMessageElement(conversationId?: string): HTMLElement | null {
  if (!currentStreamingContext) return null;
  if (conversationId && currentStreamingContext.conversationId !== conversationId) return null;
  return currentStreamingContext.element;
}
