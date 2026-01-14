/**
 * Streaming message state management and updates.
 */

import { getElementById, scrollToBottom, isScrolledToBottom } from '../../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../../utils/markdown';
import { programmaticScrollToBottom } from '../../utils/thumbnails';
import { checkScrollButtonVisibility, setStreamingPausedIndicator } from '../ScrollToBottom';
import { AI_AVATAR } from '../../utils/icons';
import { createLogger } from '../../utils/logger';
import {
  STREAMING_SCROLL_THRESHOLD_PX,
  STREAMING_SCROLL_RESUME_DEBOUNCE_MS,
} from '../../config';
import {
  createThinkingIndicator,
  updateThinkingIndicator,
  finalizeThinkingIndicator,
  createThinkingState,
  addThinkingToTrace,
  addToolStartToTrace,
  updateToolDetailInTrace,
  markToolCompletedInTrace,
} from '../ThinkingIndicator';
import { createMessageActions } from './actions';
import { renderMessageFiles } from './attachments';
import type { StreamingMessageContext } from './types';
import type { Source, GeneratedImage, FileMetadata, ThinkingState, ToolMetadata } from '../../types/api';

const log = createLogger('messages');

// Global context for the current streaming message
let currentStreamingContext: StreamingMessageContext | null = null;

// Track the previous scroll position to detect scroll direction
// Used to distinguish user scrolls (up) from our programmatic scrolls (always to bottom)
let previousScrollTop = 0;

/**
 * Add a streaming message placeholder
 * @param conversationId - The ID of the conversation this streaming message belongs to
 * @returns Object with element and methods to update thinking state
 */
export function addStreamingMessage(conversationId: string): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  // Clean up any existing streaming context before creating a new one.
  // This prevents "zombie" scroll listeners if addStreamingMessage is called
  // while there's already an active streaming context (e.g., rapid message sends).
  if (currentStreamingContext) {
    log.warn('addStreamingMessage called with existing context - cleaning up previous context');
    cleanupStreamingContext();
  }

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';

  // Create thinking indicator
  const thinkingIndicator = createThinkingIndicator();
  const thinkingState = createThinkingState();

  messageEl.innerHTML = `
    <div class="message-avatar">${AI_AVATAR}</div>
    <div class="message-content-wrapper">
      <div class="message-content">
        <span class="streaming-cursor"></span>
      </div>
    </div>
  `;

  // Insert thinking indicator at the start of message-content
  const contentEl = messageEl.querySelector('.message-content');
  if (contentEl) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
  }

  // Check if user is at bottom BEFORE adding the message
  const wasAtBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

  // Store context for updates
  currentStreamingContext = {
    element: messageEl,
    thinkingIndicator,
    thinkingState,
    shouldAutoScroll: wasAtBottom,
    scrollListenerCleanup: null,
    conversationId,
  };

  container.appendChild(messageEl);
  programmaticScrollToBottom(container);

  // Set up scroll listener to detect user scroll during streaming
  // This allows interrupting auto-scroll when scrolling up and resuming when scrolling back to bottom
  setupStreamingScrollListener(container);

  // Update button visibility after adding message and scrolling
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });

  return messageEl;
}

/**
 * Set up a scroll listener for streaming that:
 * 1. IMMEDIATELY disables auto-scroll when user scrolls up (away from bottom)
 * 2. Re-enables auto-scroll (with debounce) when user scrolls back to bottom
 *
 * CRITICAL: We must distinguish between user scrolls and our programmatic scrolls.
 * Our scrollToBottom() always scrolls DOWN (increases scrollTop), so if scrollTop
 * DECREASES, it must be a user scroll. This direction-based detection is more
 * reliable than time-based detection because it works regardless of event timing.
 */
function setupStreamingScrollListener(container: HTMLElement): void {
  if (!currentStreamingContext) return;

  // Clean up any existing listener
  if (currentStreamingContext.scrollListenerCleanup) {
    currentStreamingContext.scrollListenerCleanup();
  }

  // Initialize previous scroll position
  previousScrollTop = container.scrollTop;

  // Debounce timeout is ONLY used for re-enabling auto-scroll (when user scrolls back to bottom)
  // This prevents rapid re-enabling when user is scrolling around near the bottom
  let resumeDebounceTimeout: number | undefined;

  const scrollHandler = (): void => {
    if (!currentStreamingContext) return;

    const currentScrollTop = container.scrollTop;

    // iOS Safari momentum scroll can cause scrollTop to temporarily go negative
    // (rubber-banding at top) or past the max (rubber-banding at bottom).
    // Ignore these out-of-bounds values to prevent false user-scroll detection.
    const maxScrollTop = container.scrollHeight - container.clientHeight;
    if (currentScrollTop < 0 || currentScrollTop > maxScrollTop) {
      return; // Ignore rubber-banding scroll events
    }

    const scrolledUp = currentScrollTop < previousScrollTop;
    previousScrollTop = currentScrollTop;

    // If user scrolled UP, they want to read earlier content - disable auto-scroll immediately
    // Our programmatic scrollToBottom() never scrolls up, so this is definitely a user action
    if (scrolledUp && currentStreamingContext.shouldAutoScroll) {
      currentStreamingContext.shouldAutoScroll = false;
      log.debug('Streaming auto-scroll paused (user scrolled up)');

      // Show visual indicator on scroll button
      setStreamingPausedIndicator(true);

      // Clear any pending resume timeout
      if (resumeDebounceTimeout) {
        clearTimeout(resumeDebounceTimeout);
        resumeDebounceTimeout = undefined;
      }
      return;
    }

    // Check if at bottom for re-enabling auto-scroll
    const atBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

    if (atBottom && !currentStreamingContext.shouldAutoScroll) {
      // User scrolled back to bottom - use debounce to re-enable auto-scroll
      // This prevents rapid toggling when user is scrolling around near the bottom
      if (resumeDebounceTimeout) {
        clearTimeout(resumeDebounceTimeout);
      }

      resumeDebounceTimeout = window.setTimeout(() => {
        if (!currentStreamingContext) return;

        // Re-check position after debounce (user might have scrolled away again)
        const stillAtBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);
        if (stillAtBottom && !currentStreamingContext.shouldAutoScroll) {
          currentStreamingContext.shouldAutoScroll = true;
          log.debug('Streaming auto-scroll resumed (user scrolled to bottom)');

          // Clear the visual indicator
          setStreamingPausedIndicator(false);
        }
        resumeDebounceTimeout = undefined;
      }, STREAMING_SCROLL_RESUME_DEBOUNCE_MS);
    }
  };

  container.addEventListener('scroll', scrollHandler, { passive: true });

  // Store cleanup function
  currentStreamingContext.scrollListenerCleanup = () => {
    if (resumeDebounceTimeout) {
      clearTimeout(resumeDebounceTimeout);
    }
    container.removeEventListener('scroll', scrollHandler);
  };
}

/**
 * Clean up streaming context and scroll listener.
 * Called when streaming ends (success or error).
 */
export function cleanupStreamingContext(): void {
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

/**
 * Restore a streaming message UI when switching back to a conversation with an active stream.
 * This re-creates the streaming message element with the accumulated content and thinking state.
 * @param conversationId - The ID of the conversation this streaming message belongs to
 * @param content - The accumulated content so far
 * @param thinkingState - The thinking state to restore
 */
export function restoreStreamingMessage(conversationId: string, content: string, thinkingState?: ThinkingState): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  // Clean up any existing streaming context first (this shouldn't happen normally
  // since switchToConversation should only clean up when switching to a different conversation)
  cleanupStreamingContext();

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';

  // Create thinking indicator with the restored state
  const thinkingIndicator = createThinkingIndicator();
  const restoredThinkingState = thinkingState ?? createThinkingState();

  messageEl.innerHTML = `
    <div class="message-avatar">${AI_AVATAR}</div>
    <div class="message-content-wrapper">
      <div class="message-content">
        <span class="streaming-cursor"></span>
      </div>
    </div>
  `;

  // Insert thinking indicator at the start of message-content
  const contentEl = messageEl.querySelector('.message-content');
  if (contentEl) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);

    // Render existing content if any
    if (content) {
      contentEl.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';
      // Re-insert thinking indicator at the top
      contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
    }
  }

  // Check if user is at bottom BEFORE adding the message
  const wasAtBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

  // Store context for updates
  currentStreamingContext = {
    element: messageEl,
    thinkingIndicator,
    thinkingState: restoredThinkingState,
    shouldAutoScroll: wasAtBottom,
    scrollListenerCleanup: null,
    conversationId,
  };

  // Update thinking indicator with the restored state
  updateThinkingIndicator(thinkingIndicator, restoredThinkingState);

  container.appendChild(messageEl);
  programmaticScrollToBottom(container);

  // Reset previousScrollTop to current position AFTER scroll completes
  // This prevents the first scroll event after restore from incorrectly detecting "user scrolled up"
  requestAnimationFrame(() => {
    previousScrollTop = container.scrollTop;
  });

  // Set up scroll listener
  setupStreamingScrollListener(container);

  // Update button visibility
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });

  log.debug('Restored streaming message', { contentLength: content.length, hasThinkingState: !!thinkingState });

  return messageEl;
}

/**
 * Auto-scroll to keep the thinking indicator visible during streaming.
 * Only scrolls if auto-scroll is enabled (controlled by the scroll listener).
 *
 * Note: We CANNOT check isScrolledToBottom() here because when new content is added,
 * scrollHeight increases, making the user appear "not at bottom" even though they
 * never scrolled. The scroll listener handles detecting actual user scrolls by
 * checking scroll direction (scrollTop decreasing = user scrolled up).
 *
 * However, we DO check if scrollTop has decreased since last check to catch cases
 * where the user scrolled up but the scroll event hasn't fired yet (race condition).
 *
 * IMPORTANT: Both this function and setupStreamingScrollListener() can detect user
 * scroll-up. Both MUST call setStreamingPausedIndicator() to keep the visual state
 * consistent with shouldAutoScroll.
 */
function autoScrollForStreaming(): void {
  if (!currentStreamingContext?.shouldAutoScroll) return;

  const messagesContainer = getElementById('messages');
  if (!messagesContainer) return;

  // Synchronous check: if scrollTop has decreased, user scrolled up
  // This catches race conditions where user scrolls up but scroll event hasn't fired yet
  const currentScrollTop = messagesContainer.scrollTop;
  if (currentScrollTop < previousScrollTop) {
    // User scrolled up - disable auto-scroll immediately
    currentStreamingContext.shouldAutoScroll = false;
    log.debug('Streaming auto-scroll paused (detected user scroll up synchronously)');

    // Show visual indicator on scroll button (same as scroll handler)
    setStreamingPausedIndicator(true);

    previousScrollTop = currentScrollTop;
    return;
  }

  // Update previousScrollTop before scrolling (scrollToBottom will increase it)
  previousScrollTop = currentScrollTop;

  scrollToBottom(messagesContainer);
}

/**
 * Update the thinking state of the current streaming message
 */
export function updateStreamingThinking(thinkingText?: string): void {
  if (!currentStreamingContext) return;

  if (thinkingText) {
    addThinkingToTrace(currentStreamingContext.thinkingState, thinkingText);
  }
  currentStreamingContext.thinkingState.isThinking = true;

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll to keep thinking indicator visible
  autoScrollForStreaming();
}

/**
 * Signal that a tool has started executing
 * @param toolName The name of the tool
 * @param detail Optional detail (search query, URL, prompt)
 * @param metadata Optional metadata from backend for display (label, icon)
 */
export function updateStreamingToolStart(
  toolName: string,
  detail?: string,
  metadata?: ToolMetadata
): void {
  if (!currentStreamingContext) return;

  addToolStartToTrace(currentStreamingContext.thinkingState, toolName, detail, metadata);

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll to keep tool indicator visible
  autoScrollForStreaming();
}

/**
 * Update the detail for an active tool (e.g., when streaming args become available)
 * @param toolName The name of the tool
 * @param detail The detail to show (e.g., action, query)
 */
export function updateStreamingToolDetail(toolName: string, detail: string): void {
  if (!currentStreamingContext) return;

  updateToolDetailInTrace(currentStreamingContext.thinkingState, toolName, detail);

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll to keep tool indicator visible
  autoScrollForStreaming();
}

/**
 * Signal that a tool has finished executing
 */
export function updateStreamingToolEnd(toolName: string): void {
  if (!currentStreamingContext) return;

  markToolCompletedInTrace(currentStreamingContext.thinkingState, toolName);

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll after tool completion
  autoScrollForStreaming();
}

/**
 * Update streaming message content
 */
export function updateStreamingMessage(
  messageEl: HTMLElement,
  content: string
): void {
  const contentEl = messageEl.querySelector('.message-content');
  if (!contentEl) return;

  // Preserve thinking indicator if it exists
  const thinkingIndicator = contentEl.querySelector('.thinking-indicator');

  // Render markdown for the accumulated content
  contentEl.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';

  // Re-insert thinking indicator at the top
  if (thinkingIndicator) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
  }

  // When content starts flowing, mark thinking as done
  if (content && currentStreamingContext) {
    currentStreamingContext.thinkingState.isThinking = false;
    updateThinkingIndicator(
      currentStreamingContext.thinkingIndicator,
      currentStreamingContext.thinkingState
    );
  }

  // Auto-scroll if user was at bottom when streaming started
  autoScrollForStreaming();
}

/**
 * Finalize streaming message
 */
export function finalizeStreamingMessage(
  messageEl: HTMLElement,
  messageId: string,
  createdAt?: string,
  sources?: Source[],
  generatedImages?: GeneratedImage[],
  files?: FileMetadata[],
  role: 'user' | 'assistant' = 'assistant',
  language?: string
): void {
  messageEl.classList.remove('streaming');
  messageEl.dataset.messageId = messageId;

  // Remove cursor
  const cursor = messageEl.querySelector('.streaming-cursor');
  cursor?.remove();

  // Finalize thinking indicator and clean up streaming context
  if (currentStreamingContext && currentStreamingContext.element === messageEl) {
    finalizeThinkingIndicator(
      currentStreamingContext.thinkingIndicator,
      currentStreamingContext.thinkingState
    );
    // Clean up scroll listener
    if (currentStreamingContext.scrollListenerCleanup) {
      currentStreamingContext.scrollListenerCleanup();
    }

    // Ensure the streaming paused indicator is cleared
    setStreamingPausedIndicator(false);

    // Clear the context
    currentStreamingContext = null;
  }

  // Apply syntax highlighting to code blocks
  const content = messageEl.querySelector('.message-content');
  if (content) {
    highlightAllCodeBlocks(content as HTMLElement);

    // Add files (generated images) inside the content bubble
    if (files && files.length > 0) {
      const filesContainer = renderMessageFiles(files, messageId);
      content.appendChild(filesContainer);
    }
  }

  // Add message actions (timestamp + sources/imagegen buttons + copy button)
  const contentWrapper = messageEl.querySelector('.message-content-wrapper');
  if (contentWrapper && !contentWrapper.querySelector('.message-actions')) {
    const actions = createMessageActions(
      messageId,
      createdAt,
      sources,
      generatedImages,
      role,
      language
    );
    contentWrapper.appendChild(actions);
  }

  // Update button visibility after finalizing message
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });
}
