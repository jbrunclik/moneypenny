/**
 * Streaming message state management and updates.
 */

import { createElement, getElementById, isScrolledToBottom } from '../../utils/dom';
import { updateLatestAssistantMarker } from './render';
import { renderMarkdown, highlightAllCodeBlocks } from '../../utils/markdown';
import { renderMermaidIn } from '../../utils/mermaid';
import { highlightLiveCodeBlocks } from './live-highlight';
import { programmaticScrollToBottom } from '../../utils/programmatic-scroll';
import { kbDebugEvent } from '../../core/keyboard-viewport';
import { checkScrollButtonVisibility, setStreamingPausedIndicator } from '../ScrollToBottom';
import { AI_AVATAR, createIconElement } from '../../utils/icons';
import { createLogger } from '../../utils/logger';
import { STREAMING_SCROLL_THRESHOLD_PX } from '../../config';
import {
  createThinkingIndicator,
  updateThinkingIndicator,
  finalizeThinkingIndicator,
  collapseThinkingIndicator,
  createThinkingState,
} from '../ThinkingIndicator';
import { createMessageActions } from './actions';
import { anchorTurn } from './turn-anchor';
import { renderMessageFiles } from './attachments';
import { lockOlderQuizBlocks } from './render';
import {
  cleanupStreamingContext,
  getStreamingContext,
  setStreamingContext,
} from './streaming-context';
import { autoScrollForStreaming, setupStreamingScrollListener } from './stream-follow';
import { clearStreamingRetryStatus } from './stream-progress';
import type { Source, GeneratedImage, FileMetadata, ThinkingState } from '../../types/api';

const log = createLogger('messages');

/**
 * Add a streaming message placeholder
 * @param conversationId - The ID of the conversation this streaming message belongs to
 * @returns Object with element and methods to update thinking state
 */
/** The streaming bubble's avatar and content (an empty reply with the cursor). */
function appendStreamingBubble(messageEl: HTMLElement): void {
  messageEl.append(
    createIconElement('message-avatar', AI_AVATAR, 'div'),
    createElement('div', { class: 'message-content-wrapper' }, [
      createElement('div', { class: 'message-content' }, [createElement('span', { class: 'streaming-cursor' })]),
    ])
  );
}

export function addStreamingMessage(
  conversationId: string,
  { anchor = true }: { anchor?: boolean } = {}
): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  // Clean up any existing streaming context before creating a new one.
  // This prevents "zombie" scroll listeners if addStreamingMessage is called
  // while there's already an active streaming context (e.g., rapid message sends).
  if (getStreamingContext()) {
    log.warn('addStreamingMessage called with existing context - cleaning up previous context');
    cleanupStreamingContext();
  }

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';
  // Announce streamed content to screen readers without interrupting
  messageEl.setAttribute('role', 'log');
  messageEl.setAttribute('aria-live', 'polite');

  // Create thinking indicator
  const thinkingIndicator = createThinkingIndicator();
  const thinkingState = createThinkingState();

  appendStreamingBubble(messageEl);

  // Insert thinking indicator at the start of message-content
  const contentEl = messageEl.querySelector('.message-content');
  if (contentEl) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
  }

  // The turn this reply answers: the user's message just sent (or being
  // regenerated) or a program's auto-start trigger chip, else the reply
  // itself (Continue appends a new bubble after the previous reply)
  const previous = container.lastElementChild;
  const turnEl =
    previous instanceof HTMLElement && previous.matches('.message:not(.assistant)') ? previous : messageEl;

  // Send-to-top: the view stays on the turn instead of following the reply
  // down; scrolling to the bottom (or the pill) re-arms following
  setStreamingContext({
    element: messageEl,
    thinkingIndicator,
    thinkingState,
    shouldAutoScroll: false,
    scrollListenerCleanup: null,
    conversationId,
    hasReplyText: false,
  });

  container.appendChild(messageEl);
  // anchor=false: following another device's reply while the user reads
  // further up - leave the view alone (the pill offers the new content)
  if (anchor) anchorTurn(container, turnEl, messageEl);
  logThinkingBarPosition(thinkingIndicator);

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
 * kbdebug overlay only: where the new thinking bar sits relative to the
 * composer pill, now and as layout settles (iOS PWA: it can end up behind the
 * composer - TODO.md). `gap` < 0 means the bar is covered.
 */
function logThinkingBarPosition(bar: HTMLElement): void {
  const snap = (label: string): void => {
    const pill = document.getElementById('input-container')?.getBoundingClientRect();
    const r = bar.getBoundingClientRect();
    kbDebugEvent(label, {
      barTop: Math.round(r.top),
      barBot: Math.round(r.bottom),
      pillTop: pill ? Math.round(pill.top) : null,
      gap: pill ? Math.round(pill.top - r.bottom) : null,
      follow: getStreamingContext()?.shouldAutoScroll ?? null,
    });
  };
  requestAnimationFrame(() => snap('bar@0'));
  setTimeout(() => snap('bar@300'), 300);
  setTimeout(() => snap('bar@1000'), 1000);
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
  // Announce streamed content to screen readers without interrupting
  messageEl.setAttribute('role', 'log');
  messageEl.setAttribute('aria-live', 'polite');

  // Create thinking indicator with the restored state
  const thinkingIndicator = createThinkingIndicator();
  const restoredThinkingState = thinkingState ?? createThinkingState();

  appendStreamingBubble(messageEl);

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
  setStreamingContext({
    element: messageEl,
    thinkingIndicator,
    thinkingState: restoredThinkingState,
    shouldAutoScroll: wasAtBottom,
    scrollListenerCleanup: null,
    conversationId,
    hasReplyText: content.trim() !== '',
  });

  // Update thinking indicator with the restored state
  updateThinkingIndicator(thinkingIndicator, restoredThinkingState);
  if (content.trim()) collapseThinkingIndicator(thinkingIndicator, restoredThinkingState);

  container.appendChild(messageEl);
  programmaticScrollToBottom(container);

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
 * Update streaming message content
 */
export function updateStreamingMessage(
  messageEl: HTMLElement,
  content: string
): void {
  clearStreamingRetryStatus();
  const contentEl = messageEl.querySelector('.message-content');
  if (!contentEl) return;

  // Preserve thinking indicator if it exists
  const thinkingIndicator = contentEl.querySelector('.thinking-indicator');

  // Render markdown for the accumulated content
  contentEl.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';

  // Live syntax highlighting: completed blocks come from the per-block
  // cache; only the still-growing block is re-highlighted
  highlightLiveCodeBlocks(contentEl as HTMLElement);

  // Re-insert thinking indicator at the top
  if (thinkingIndicator) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
  }

  // When the answer starts: thinking is done, and its line collapses to
  // the summary so the answer starts right under the user's message (a
  // later round's thinking or tool reopens it)
  const context = getStreamingContext();
  if (content && context) {
    context.hasReplyText = true;
    context.thinkingState.isThinking = false;
    collapseThinkingIndicator(
      context.thinkingIndicator,
      context.thinkingState
    );
  }

  // Auto-scroll if user was at bottom when streaming started
  autoScrollForStreaming();
}

/**
 * Finalize streaming message.
 * @returns Whether the user was following (auto-scroll was active) when streaming ended.
 *          Returns false if user had scrolled away during streaming.
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
): boolean {
  messageEl.classList.remove('streaming');
  // Stop live-region announcements once the message is final
  messageEl.removeAttribute('role');
  messageEl.removeAttribute('aria-live');
  messageEl.dataset.messageId = messageId;

  // Remove cursor
  const cursor = messageEl.querySelector('.streaming-cursor');
  cursor?.remove();

  // Capture whether user was following before cleaning up context
  let wasFollowing = false;

  clearStreamingRetryStatus();

  // Finalize thinking indicator and clean up streaming context
  const context = getStreamingContext();
  if (context && context.element === messageEl) {
    // Capture auto-scroll state before cleanup
    wasFollowing = context.shouldAutoScroll;

    finalizeThinkingIndicator(
      context.thinkingIndicator,
      context.thinkingState
    );
    // Clean up scroll listener
    if (context.scrollListenerCleanup) {
      context.scrollListenerCleanup();
    }

    // Ensure the streaming paused indicator is cleared
    setStreamingPausedIndicator(false);

    // Clear the context
    setStreamingContext(null);
  }

  // Apply syntax highlighting to code blocks
  const content = messageEl.querySelector('.message-content');
  if (content) {
    highlightAllCodeBlocks(content as HTMLElement);
    void renderMermaidIn(content as HTMLElement); // diagrams once the text is final

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

  // The finalized message is now the latest assistant turn - reveal
  // regenerate/continue on it (and hide them on the previous one)
  updateLatestAssistantMarker();

  // Lock quiz blocks in older messages now that this one is the latest
  lockOlderQuizBlocks();

  // Update button visibility after finalizing message
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });

  return wasFollowing;
}
