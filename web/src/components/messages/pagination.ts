/**
 * Message pagination - loading older and newer messages via infinite scroll.
 */

import { getElementById } from '../../utils/dom';
import { onMessagesScroll, offMessagesScroll } from '../../utils/scroll-manager';
import { observeThumbnail, beginProgrammaticScroll, endProgrammaticScroll } from '../../utils/thumbnails';
import { conversations } from '../../api/conversations';
import { useStore } from '../../state/store';
import { createLogger } from '../../utils/logger';
import {
  LOAD_OLDER_MESSAGES_THRESHOLD_PX,
  LOAD_NEWER_MESSAGES_THRESHOLD_PX,
  INFINITE_SCROLL_DEBOUNCE_MS,
} from '../../config';
import { PaginationDirection } from '../../types/api';
import { addMessageToUI, lockOlderQuizBlocks } from './render';
import { applyCompactionMarkers } from '../CompactionIndicator';
import type { Message } from '../../types/api';

const log = createLogger('messages');

// =============================================================================
// Older Messages Pagination
// =============================================================================

/** Cleanup function for the older messages scroll listener */
let olderMessagesScrollCleanup: (() => void) | null = null;

/**
 * Set up a scroll listener to load older messages when user scrolls near the top.
 * Should be called after rendering messages for a conversation.
 * @param conversationId - The ID of the current conversation
 */
export function setupOlderMessagesScrollListener(conversationId: string): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Clean up any existing listener first
  cleanupOlderMessagesScrollListener();

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = (): void => {
    // Debounce the scroll handler
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = setTimeout(() => {
      const store = useStore.getState();

      // Don't load older messages during active streaming
      // This prevents interference with streaming auto-scroll behavior
      if (store.streamingConversationId === conversationId) {
        return;
      }

      const pagination = store.getMessagesPagination(conversationId);

      // Don't load more if already loading or no more older messages
      if (!pagination || pagination.isLoadingOlder || !pagination.hasOlder) {
        return;
      }

      // Check if user is near the top
      const scrollTop = container.scrollTop;

      if (scrollTop < LOAD_OLDER_MESSAGES_THRESHOLD_PX) {
        loadOlderMessages(conversationId, container);
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  onMessagesScroll('pagination-older', handleScroll);

  // Store cleanup function
  olderMessagesScrollCleanup = () => {
    offMessagesScroll('pagination-older');
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };

  log.debug('Older messages scroll listener set up', { conversationId });
}

/**
 * Clean up the older messages scroll listener.
 * Should be called when switching conversations or unmounting.
 */
export function cleanupOlderMessagesScrollListener(): void {
  if (olderMessagesScrollCleanup) {
    olderMessagesScrollCleanup();
    olderMessagesScrollCleanup = null;
    log.debug('Older messages scroll listener cleaned up');
  }
}

/**
 * Load older messages for a conversation and prepend them to the UI.
 */
async function loadOlderMessages(conversationId: string, container: HTMLElement): Promise<void> {
  const store = useStore.getState();

  // Guard: Only load if this is still the current conversation
  // This prevents race conditions where the scroll listener fires after
  // the user has already switched to a different conversation
  if (store.currentConversation?.id !== conversationId) {
    log.debug('Skipping older messages load - conversation changed', {
      requestedId: conversationId,
      currentId: store.currentConversation?.id,
    });
    return;
  }

  const pagination = store.getMessagesPagination(conversationId);

  if (!pagination || !pagination.hasOlder || pagination.isLoadingOlder) {
    return;
  }

  log.debug('Loading older messages', { conversationId, cursor: pagination.olderCursor });

  // Set loading state
  store.setLoadingOlderMessages(conversationId, true);

  // Record the scroll height BEFORE the loader goes in: it is removed again
  // (finally) before the compensation below runs, so measuring with it
  // included left the content shifted by the loader's height for good
  const previousScrollHeight = container.scrollHeight;

  // Show loading indicator at top
  showOlderMessagesLoader(container);

  try {
    const result = await conversations.getMessages(
      conversationId,
      undefined, // use default limit
      pagination.olderCursor,
      PaginationDirection.OLDER
    );

    // Guard again after async operation - user might have switched conversations
    if (store.currentConversation?.id !== conversationId) {
      log.debug('Discarding older messages - conversation changed during load', {
        requestedId: conversationId,
        currentId: store.currentConversation?.id,
      });
      store.setLoadingOlderMessages(conversationId, false);
      hideOlderMessagesLoader();
      return;
    }

    // Update store with new messages prepended
    store.prependMessages(conversationId, result.messages, result.pagination);

    // Prepend messages to the UI
    const prepended = prependMessagesToUI(result.messages, container);

    // Restore scroll position so the user stays at the same place
    // After prepending, scrollHeight increases, so we need to adjust scrollTop
    // We also need to track image loads and re-adjust after images load to prevent drift
    requestAnimationFrame(() => {
      const newScrollHeight = container.scrollHeight;
      const scrollHeightDiff = newScrollHeight - previousScrollHeight;
      const targetScrollTop = container.scrollTop + scrollHeightDiff;
      endProgrammaticScroll(beginProgrammaticScroll()); // ours, not the user's scroll
      container.scrollTop = targetScrollTop;

      // Track images in the prepended batch and re-adjust scroll position after they load
      // This prevents scroll drift when lazy-loaded images change the scrollHeight
      trackPrependedImagesForScrollAdjustment(container, prepended);
    });

    log.info('Loaded older messages', {
      conversationId,
      count: result.messages.length,
      hasOlder: result.pagination.has_older,
    });
  } catch (error) {
    log.error('Failed to load older messages', { error, conversationId });
    // Reset loading state on error
    store.setLoadingOlderMessages(conversationId, false);
  } finally {
    hideOlderMessagesLoader();
  }
}

/**
 * Show a loading indicator at the top of the messages container.
 * For planner view, inserts after the dashboard element to keep it as first element.
 */
function showOlderMessagesLoader(container: HTMLElement): void {
  // Remove any existing loader
  hideOlderMessagesLoader();

  const loader = document.createElement('div');
  loader.className = 'older-messages-loader';
  loader.innerHTML = `
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;

  // Check if there's a dashboard element (planner view)
  const dashboard = container.querySelector('.planner-dashboard-message');
  if (dashboard && dashboard.nextSibling) {
    // Insert after dashboard to keep it as first element
    container.insertBefore(loader, dashboard.nextSibling);
  } else {
    // Normal insertion at the beginning
    container.insertBefore(loader, container.firstChild);
  }
}

/**
 * Hide the older messages loading indicator.
 */
function hideOlderMessagesLoader(): void {
  const loader = document.querySelector('.older-messages-loader');
  loader?.remove();
}

/**
 * Prepend messages to the UI at the top of the messages container.
 * Uses addMessageToUI for each message to avoid code duplication.
 * @param messages - Messages to prepend (should be in chronological order, oldest first)
 * @param container - The messages container element
 */
function prependMessagesToUI(messages: Message[], container: HTMLElement): HTMLElement[] {
  if (messages.length === 0) return [];
  const prepended: HTMLElement[] = [];

  // Find the first message element (skip loaders/welcome messages)
  const firstMessage = container.querySelector('.message');

  // Add messages in chronological order, each one inserted before the first existing message
  // This maintains chronological order: oldest prepended message ends up first
  messages.forEach((msg) => {
    // Create a temporary container to hold the new message
    const tempContainer = document.createElement('div');
    addMessageToUI(msg, tempContainer);
    const messageEl = tempContainer.firstElementChild;

    if (messageEl instanceof HTMLElement) {
      prepended.push(messageEl);
      if (firstMessage) {
        // Insert before the first existing message
        container.insertBefore(messageEl, firstMessage);
      } else {
        // No messages yet, just append
        container.appendChild(messageEl);
      }
    }
  });

  // Observe any new images for lazy loading
  const newImages = container.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]:not([src])'
  );
  newImages.forEach((img) => {
    observeThumbnail(img);
  });

  lockOlderQuizBlocks(container);
  // The boundary message may have just been loaded
  applyCompactionMarkers(container);

  log.debug('Prepended messages to UI', { count: messages.length });
  return prepended;
}

/**
 * Keep the reading position while images in the prepended page load: each
 * image that grows ABOVE the viewport pushes the content the user is reading
 * down by exactly its own growth, so add that to scrollTop.
 *
 * Per image, not per scrollHeight: comparing against the container's height
 * from when the page loaded also counted everything that grew since - a
 * streamed reply, images below the viewport - and threw the list down by
 * all of it. Only the prepended page's images are tracked (the whole list's
 * lazy images used to be, src-less ones included).
 */
function trackPrependedImagesForScrollAdjustment(container: HTMLElement, prepended: HTMLElement[]): void {
  let pendingLoads = 0;

  prepended.forEach((messageEl) => {
    messageEl.querySelectorAll<HTMLImageElement>('img[data-message-id][data-file-index]').forEach((img) => {
      if (img.complete && img.naturalHeight > 0) return; // already laid out
      const heightBefore = img.offsetHeight;
      const onSettled = (): void => {
        requestAnimationFrame(() => {
          // A conversation switch detached it - never touch the new list
          if (!img.isConnected) return;
          const growth = img.offsetHeight - heightBefore;
          const aboveViewport = img.getBoundingClientRect().top < container.getBoundingClientRect().top;
          if (growth !== 0 && aboveViewport) {
            endProgrammaticScroll(beginProgrammaticScroll()); // ours, not the user's scroll
            container.scrollTop += growth;
          }
        });
      };
      pendingLoads++;
      img.addEventListener('load', onSettled, { once: true });
      img.addEventListener('error', onSettled, { once: true });
    });
  });

  if (pendingLoads > 0) {
    log.debug('Tracking prepended images for scroll adjustment', { pendingLoads });
  }
}

// =============================================================================
// Newer Messages Pagination
// =============================================================================

/** Cleanup function for the newer messages scroll listener */
let newerMessagesScrollCleanup: (() => void) | null = null;

/**
 * Set up a scroll listener to load newer messages when user scrolls near the bottom.
 * Used after navigating to a search result in the middle of conversation history.
 * Should be called after loading messages with around_message_id.
 * @param conversationId - The ID of the current conversation
 */
export function setupNewerMessagesScrollListener(conversationId: string): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Clean up any existing listener first
  cleanupNewerMessagesScrollListener();

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = (): void => {
    // Debounce the scroll handler
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = setTimeout(() => {
      const store = useStore.getState();

      // Don't load newer messages during active streaming
      // This prevents interference with streaming auto-scroll behavior
      if (store.streamingConversationId === conversationId) {
        return;
      }

      const pagination = store.getMessagesPagination(conversationId);

      // Don't load more if already loading or no more newer messages
      if (!pagination || pagination.isLoadingNewer || !pagination.hasNewer) {
        return;
      }

      // Check if user is near the bottom
      const scrollTop = container.scrollTop;
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

      if (distanceFromBottom < LOAD_NEWER_MESSAGES_THRESHOLD_PX) {
        loadNewerMessages(conversationId, container);
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  onMessagesScroll('pagination-newer', handleScroll);

  // Store cleanup function
  newerMessagesScrollCleanup = () => {
    offMessagesScroll('pagination-newer');
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };

  log.debug('Newer messages scroll listener set up', { conversationId });
}

/**
 * Clean up the newer messages scroll listener.
 * Should be called when switching conversations or unmounting.
 */
export function cleanupNewerMessagesScrollListener(): void {
  if (newerMessagesScrollCleanup) {
    newerMessagesScrollCleanup();
    newerMessagesScrollCleanup = null;
    log.debug('Newer messages scroll listener cleaned up');
  }
}

/**
 * Load newer messages for a conversation and append them to the UI.
 */
async function loadNewerMessages(conversationId: string, container: HTMLElement): Promise<void> {
  const store = useStore.getState();

  // Guard: Only load if this is still the current conversation
  // This prevents race conditions where the scroll listener fires after
  // the user has already switched to a different conversation
  if (store.currentConversation?.id !== conversationId) {
    log.debug('Skipping newer messages load - conversation changed', {
      requestedId: conversationId,
      currentId: store.currentConversation?.id,
    });
    return;
  }

  const pagination = store.getMessagesPagination(conversationId);

  if (!pagination || !pagination.hasNewer || pagination.isLoadingNewer) {
    return;
  }

  log.debug('Loading newer messages', { conversationId, cursor: pagination.newerCursor });

  // Set loading state
  store.setLoadingNewerMessages(conversationId, true);

  // Show loading indicator at bottom
  showNewerMessagesLoader(container);

  try {
    const result = await conversations.getMessages(
      conversationId,
      undefined, // use default limit
      pagination.newerCursor,
      PaginationDirection.NEWER
    );

    // Guard again after async operation - user might have switched conversations
    if (store.currentConversation?.id !== conversationId) {
      log.debug('Discarding newer messages - conversation changed during load', {
        requestedId: conversationId,
        currentId: store.currentConversation?.id,
      });
      store.setLoadingNewerMessages(conversationId, false);
      hideNewerMessagesLoader();
      return;
    }

    // Update store with new messages appended
    store.appendMessages(conversationId, result.messages, result.pagination);

    // Append messages to the UI
    appendMessagesToUI(result.messages, container);

    log.info('Loaded newer messages', {
      conversationId,
      count: result.messages.length,
      hasNewer: result.pagination.has_newer,
    });
  } catch (error) {
    log.error('Failed to load newer messages', { error, conversationId });
    // Reset loading state on error
    store.setLoadingNewerMessages(conversationId, false);
  } finally {
    hideNewerMessagesLoader();
  }
}

/**
 * Show a loading indicator at the bottom of the messages container.
 */
function showNewerMessagesLoader(container: HTMLElement): void {
  // Remove any existing loader
  hideNewerMessagesLoader();

  const loader = document.createElement('div');
  loader.className = 'newer-messages-loader';
  loader.innerHTML = `
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;

  // Insert at the end of the container
  container.appendChild(loader);
}

/**
 * Hide the newer messages loading indicator.
 */
function hideNewerMessagesLoader(): void {
  const loader = document.querySelector('.newer-messages-loader');
  loader?.remove();
}

/**
 * Append messages to the UI at the bottom of the messages container.
 * Uses addMessageToUI for each message to avoid code duplication.
 * @param messages - Messages to append (should be in chronological order, oldest first)
 * @param container - The messages container element
 */
function appendMessagesToUI(messages: Message[], container: HTMLElement): void {
  if (messages.length === 0) return;

  // Add messages in chronological order at the end
  messages.forEach((msg) => {
    addMessageToUI(msg, container);
  });

  // Observe any new images for lazy loading
  const newImages = container.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]:not([src])'
  );
  newImages.forEach((img) => {
    observeThumbnail(img);
  });

  lockOlderQuizBlocks(container);

  log.debug('Appended messages to UI', { count: messages.length });
}

/**
 * Load ALL remaining newer messages for a conversation.
 * Used before sending a message when in a partial view (after search navigation).
 * This ensures there's no gap between existing messages and the new message.
 *
 * @param conversationId - The conversation ID to load messages for
 * @returns Promise that resolves when all newer messages are loaded, or rejects on error
 */
// One "load the rest" per conversation at a time: a second caller (another
// scroll-button tap, a send) waits for the running one instead of loading
// the same pages again and appending duplicates
const loadAllInFlight = new Map<string, Promise<void>>();

export function loadAllRemainingNewerMessages(conversationId: string): Promise<void> {
  const running = loadAllInFlight.get(conversationId);
  if (running) return running;
  const load = loadAllRemainingNewerMessagesOnce(conversationId).finally(() => {
    loadAllInFlight.delete(conversationId);
  });
  loadAllInFlight.set(conversationId, load);
  return load;
}

async function loadAllRemainingNewerMessagesOnce(conversationId: string): Promise<void> {
  const store = useStore.getState();
  const container = getElementById<HTMLDivElement>('messages');

  if (!container) {
    throw new Error('Messages container not found');
  }

  let pagination = store.getMessagesPagination(conversationId);

  // Nothing to load if no newer messages
  if (!pagination || !pagination.hasNewer) {
    log.debug('No newer messages to load', { conversationId });
    return;
  }

  log.info('Loading all remaining newer messages before send', { conversationId });

  // Show loading indicator at bottom while loading
  showNewerMessagesLoader(container);

  let totalLoaded = 0;
  const maxBatches = 50; // Safety limit to prevent infinite loops
  let batchCount = 0;

  try {
    while (pagination && pagination.hasNewer && pagination.newerCursor && batchCount < maxBatches) {
      batchCount++;

      // Guard: Check if conversation changed
      if (store.currentConversation?.id !== conversationId) {
        log.debug('Conversation changed during newer messages load', { conversationId });
        throw new Error('Conversation changed');
      }

      const result = await conversations.getMessages(
        conversationId,
        undefined, // use default limit
        pagination.newerCursor,
        PaginationDirection.NEWER
      );

      // Guard again after async operation
      if (store.currentConversation?.id !== conversationId) {
        log.debug('Conversation changed during newer messages load (post-fetch)', { conversationId });
        throw new Error('Conversation changed');
      }

      // Update store with new messages appended
      store.appendMessages(conversationId, result.messages, result.pagination);

      // Append messages to the UI
      appendMessagesToUI(result.messages, container);

      totalLoaded += result.messages.length;

      // Get updated pagination state
      pagination = store.getMessagesPagination(conversationId);

      log.debug('Loaded batch of newer messages', {
        conversationId,
        batchCount,
        batchSize: result.messages.length,
        totalLoaded,
        hasNewer: result.pagination.has_newer,
      });
    }

    if (batchCount >= maxBatches) {
      log.warn('Reached max batches while loading newer messages', { conversationId, maxBatches });
    }

    log.info('Finished loading all newer messages', { conversationId, totalLoaded, batchCount });
  } finally {
    hideNewerMessagesLoader();
  }
}
