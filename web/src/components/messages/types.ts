/**
 * Types and interfaces for the Messages component modules.
 */

import type { ThinkingState } from '../../types/api';

/**
 * Options for rendering messages
 */
export interface RenderMessagesOptions {
  /**
   * If true, skip the automatic scroll-to-bottom after rendering.
   * Useful when the caller wants to scroll to a specific message (e.g., search navigation).
   */
  skipScrollToBottom?: boolean;

  /**
   * Override for pending approval state from the server.
   * If provided, this takes precedence over the message content check.
   * This ensures the input is blocked even if the client's message parsing
   * doesn't detect a pending approval (e.g., race conditions).
   */
  hasPendingApproval?: boolean;
}

/**
 * Streaming message context - holds state for the current streaming message
 */
export interface StreamingMessageContext {
  element: HTMLElement;
  thinkingIndicator: HTMLElement;
  thinkingState: ThinkingState;
  /** Whether to auto-scroll during streaming - dynamically updated based on user scroll */
  shouldAutoScroll: boolean;
  /** Scroll listener cleanup function */
  scrollListenerCleanup: (() => void) | null;
  /** Conversation ID this streaming context belongs to */
  conversationId: string;
}
