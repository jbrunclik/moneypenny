/**
 * Search module.
 * Handles search result navigation and message highlighting.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations, ApiError } from '../api/client';
import { toast } from '../components/Toast';
import { closeSidebar } from '../components/Sidebar';
import {
  renderMessages,
  setupOlderMessagesScrollListener,
  setupNewerMessagesScrollListener,
} from '../components/messages';
import { getElementById } from '../utils/dom';
import { disableScrollOnImageLoad } from '../utils/thumbnails';
import { getSyncManager } from '../sync/SyncManager';
import { SEARCH_HIGHLIGHT_DURATION_MS, SEARCH_RESULT_MESSAGES_LIMIT } from '../config';

import { selectConversation } from './conversation';

const log = createLogger('search');

// Track the most recently requested message ID for search navigation
// This prevents stale API responses from rendering when user clicks multiple search results quickly
let pendingSearchNavigationMessageId: string | null = null;

/**
 * Handle click on a search result - navigate to conversation and optionally scroll to message.
 * Search results stay visible so user can try other results.
 */
export async function handleSearchResultClick(convId: string, messageId: string | null, resultIndex: number): Promise<void> {
  log.debug('Search result clicked', { convId, messageId, resultIndex });

  // Track which result is being viewed (by index, not by message_id to handle duplicates)
  useStore.getState().setViewedSearchResult(resultIndex);

  // Close sidebar on mobile (user can reopen to see results)
  closeSidebar();

  // Navigate to the conversation
  await navigateToSearchResult(convId, messageId);
}

/**
 * Navigate to a conversation from search result and highlight the matching message.
 */
async function navigateToSearchResult(convId: string, messageId: string | null): Promise<void> {
  const store = useStore.getState();
  const { currentConversation, streamingConversationId } = store;

  // Check if we're already viewing this conversation
  if (currentConversation?.id === convId) {
    // If streaming is active in this conversation, don't navigate away from the current view
    // as it would break the streaming UI. Just show a toast instead.
    if (streamingConversationId === convId && messageId) {
      toast.info('Please wait for the response to complete.');
      return;
    }

    // Already viewing - just scroll to message if provided
    if (messageId) {
      await scrollToAndHighlightMessage(messageId);
    }
    return;
  }

  // Load and switch to the conversation
  await selectConversation(convId);

  // After loading, scroll to and highlight the message if provided
  if (messageId) {
    // Use setTimeout to ensure DOM has updated after conversation switch
    setTimeout(async () => {
      await scrollToAndHighlightMessage(messageId);
    }, 100);
  }
}

/**
 * Scroll to a message and apply highlight animation.
 * If the message isn't in the current DOM (due to pagination), loads messages
 * centered around the target in a single API call using around_message_id.
 */
async function scrollToAndHighlightMessage(messageId: string): Promise<void> {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) {
    return;
  }

  const store = useStore.getState();
  const { currentConversation, streamingConversationId } = store;
  if (!currentConversation) {
    return;
  }

  // Don't perform search navigation while streaming is active in this conversation
  // as loading messages around the target would break the streaming UI
  if (streamingConversationId === currentConversation.id) {
    log.debug('Skipping search navigation while streaming is active', {
      conversationId: currentConversation.id,
    });
    return;
  }

  // Track this navigation request - if another navigation starts, we'll abort this one
  pendingSearchNavigationMessageId = messageId;

  // Try to find the message element in the current DOM first
  let messageEl = messagesContainer.querySelector<HTMLDivElement>(`.message[data-message-id="${messageId}"]`);

  // If not found in DOM, use around_message_id to load messages centered on the target
  if (!messageEl) {
    log.debug('Message not in DOM, loading messages around target', { messageId });

    try {
      // Single API call to get messages centered around the target
      const response = await conversations.getMessagesAround(
        currentConversation.id,
        messageId,
        SEARCH_RESULT_MESSAGES_LIMIT
      );

      // Guard: Check if user clicked a different search result during the API call
      if (pendingSearchNavigationMessageId !== messageId) {
        log.debug('Search navigation cancelled - user clicked different result', {
          originalMessageId: messageId,
          newMessageId: pendingSearchNavigationMessageId,
        });
        return;
      }

      // Guard: Check if user switched conversations during the API call
      const currentConvNow = useStore.getState().currentConversation;
      if (!currentConvNow || currentConvNow.id !== currentConversation.id) {
        log.debug('Conversation changed during search navigation, aborting', {
          originalConvId: currentConversation.id,
          currentConvId: currentConvNow?.id,
        });
        return;
      }

      // Replace messages in store with the new page centered on target
      store.setMessages(currentConversation.id, response.messages, response.pagination);

      // Update sync manager's local message count to match the total from pagination.
      // This prevents false unread badges when sync runs after search navigation.
      // We use the total_count from pagination, which represents ALL messages in the conversation,
      // not just the subset we loaded around the target.
      getSyncManager()?.markConversationRead(currentConversation.id, response.pagination.total_count);

      // IMPORTANT: Disable scroll-on-image-load BEFORE rendering.
      // We want to scroll to the target message, not to the bottom.
      // renderMessages() normally enables scroll-on-image-load, but we need to override that.
      disableScrollOnImageLoad();

      // Re-render messages with skipScrollToBottom: true
      // This prevents the default scroll-to-bottom behavior so we can scroll to the target instead
      renderMessages(response.messages, { skipScrollToBottom: true });

      // Set up both scroll listeners for bi-directional pagination
      // These will be cleaned up on conversation switch
      setupOlderMessagesScrollListener(currentConversation.id);
      setupNewerMessagesScrollListener(currentConversation.id);

      // Wait for layout to settle (including lazy-loaded images) before finding and scrolling
      // Use multiple RAFs to ensure images have started rendering
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            resolve();
          });
        });
      });

      // Guard again after RAFs - user might have clicked another search result
      if (pendingSearchNavigationMessageId !== messageId) {
        log.debug('Search navigation cancelled during layout - user clicked different result', {
          originalMessageId: messageId,
          newMessageId: pendingSearchNavigationMessageId,
        });
        return;
      }

      // Try to find the message element again after rendering
      messageEl = messagesContainer.querySelector<HTMLDivElement>(`.message[data-message-id="${messageId}"]`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        log.warn('Message not found via around_message_id', { messageId });
        toast.info('Message not found in this conversation.');
        return;
      }
      log.error('Failed to load messages around search result', { error, messageId });
      toast.error('Failed to navigate to message.');
      return;
    }
  }

  // If still not found after loading, show a toast
  if (!messageEl) {
    log.warn('Message element not found after loading around page', { messageId });
    toast.info('Message not found in this conversation.');
    return;
  }

  // Scroll the message into view - use 'start' to position it at the top of the viewport
  // This is better UX for long messages where 'center' would show the middle of the message
  messageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Apply highlight animation
  messageEl.classList.add('search-highlight');

  // Remove highlight class after animation completes
  setTimeout(() => {
    messageEl?.classList.remove('search-highlight');
  }, SEARCH_HIGHLIGHT_DURATION_MS);

  log.debug('Scrolled to and highlighted message', { messageId });
}
