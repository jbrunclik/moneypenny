/**
 * Stream recovery module.
 * Handles recovery of interrupted streams from mobile disconnect, network failures, and timeouts.
 *
 * The recovery logic:
 * 1. Mark a stream for recovery when interrupted (visibility hidden, network error, timeout)
 * 2. On visibility restore or manual trigger, attempt to fetch the message by its pre-generated ID
 * 3. Use exponential backoff to handle race conditions (message not yet saved)
 * 4. Update UI with recovered content or show error
 */

import { conversations as conversationsApi, ApiError } from '../api/client';
import { useStore } from '../state/store';
import { toast } from '../components/Toast';
import { createLogger } from '../utils/logger';
import {
  STREAM_RECOVERY_RETRY_DELAYS_MS,
  STREAM_RECOVERY_CONTENT_POLL_DELAYS_MS,
  STREAM_RECOVERY_MIN_HIDDEN_MS,
  STREAM_RECOVERY_DEBOUNCE_MS,
} from '../config';
import {
  updateStreamingMessage,
  finalizeStreamingMessage,
  getStreamingMessageElement,
  cleanupStreamingContext,
  addMessageToUI,
} from '../components/messages';
import { getElementById, scrollToBottom } from '../utils/dom';
import type { Message, Source, GeneratedImage, FileMetadata } from '../types/api';
import { updateConversationTitle } from './conversation';
import { updateConversationCost } from './toolbar';
import { getSyncManager } from '../sync/SyncManager';
import { hideNewMessagesAvailableBanner } from './sync-banner';

const log = createLogger('stream-recovery');

// ============ Types ============

/** Reason for stream interruption */
export type RecoveryReason = 'visibility' | 'network' | 'timeout';

/** State for a pending recovery */
interface PendingRecovery {
  conversationId: string;
  expectedMessageId: string;
  capturedContent: string;
  interruptedAt: number;
  reason: RecoveryReason;
}

// ============ State ============

/** Pending recoveries by conversation ID */
const pendingRecoveries = new Map<string, PendingRecovery>();

/** Timestamp of last recovery attempt by conversation ID (for debouncing) */
const lastRecoveryAttempt = new Map<string, number>();

/** Active recovery promises to prevent concurrent recovery for same conversation */
const activeRecoveryPromises = new Map<string, Promise<boolean>>();

// ============ Public API ============

/**
 * Mark a stream as interrupted and ready for recovery.
 * Called when:
 * - Visibility changes to hidden during streaming
 * - Network error occurs during streaming
 * - Timeout occurs during streaming
 *
 * @param convId - Conversation ID
 * @param expectedMessageId - Pre-generated assistant message ID from server
 * @param currentContent - Content received so far (for comparison)
 * @param reason - Why the stream was interrupted
 */
export function markStreamForRecovery(
  convId: string,
  expectedMessageId: string,
  currentContent: string,
  reason: RecoveryReason
): void {
  const existing = pendingRecoveries.get(convId);

  // If pending recovery exists, only update if the new reason is more severe.
  // Severity: network/timeout > visibility (because visibility has the <500ms hidden guard)
  if (existing) {
    const isUpgrade = existing.reason === 'visibility' && (reason === 'network' || reason === 'timeout');
    if (isUpgrade) {
      log.debug('Upgrading recovery reason', {
        conversationId: convId,
        oldReason: existing.reason,
        newReason: reason,
      });
      pendingRecoveries.set(convId, {
        ...existing,
        reason,
        // Update timestamp so the "<500ms hidden" guard doesn't apply
        interruptedAt: Date.now(),
      });
    } else {
      log.debug('Recovery already pending, not overwriting', {
        conversationId: convId,
        existingReason: existing.reason,
        newReason: reason,
      });
    }
    return;
  }

  pendingRecoveries.set(convId, {
    conversationId: convId,
    expectedMessageId,
    capturedContent: currentContent,
    interruptedAt: Date.now(),
    reason,
  });

  log.info('Stream marked for recovery', {
    conversationId: convId,
    expectedMessageId,
    contentLength: currentContent.length,
    reason,
  });
}

/**
 * Clear pending recovery for a conversation.
 * Called when:
 * - Stream completes successfully (done event received)
 * - Recovery succeeds
 * - User manually refreshes the conversation
 * - Stream is aborted by user
 *
 * @param convId - Conversation ID
 */
export function clearPendingRecovery(convId: string): void {
  if (pendingRecoveries.has(convId)) {
    log.debug('Clearing pending recovery', { conversationId: convId });
    pendingRecoveries.delete(convId);
    lastRecoveryAttempt.delete(convId);
    activeRecoveryPromises.delete(convId);
  }
}

/**
 * Check if there's a pending recovery for a conversation.
 *
 * @param convId - Conversation ID
 * @returns true if recovery is pending
 */
export function hasPendingRecovery(convId: string): boolean {
  return pendingRecoveries.has(convId);
}

/**
 * Get pending recovery info for a conversation.
 * Used for testing and debugging.
 *
 * @param convId - Conversation ID
 * @returns Recovery info or undefined
 */
export function getPendingRecovery(convId: string): PendingRecovery | undefined {
  return pendingRecoveries.get(convId);
}

/**
 * Attempt to recover an interrupted stream.
 * Uses exponential backoff to handle race conditions where the message
 * might not be saved yet.
 *
 * @param convId - Conversation ID to recover
 * @returns true if recovery succeeded, false otherwise
 */
export async function attemptRecovery(convId: string): Promise<boolean> {
  const pending = pendingRecoveries.get(convId);
  if (!pending) {
    log.debug('No pending recovery found', { conversationId: convId });
    return false;
  }

  // Debounce rapid recovery attempts
  const lastAttempt = lastRecoveryAttempt.get(convId) || 0;
  const timeSinceLastAttempt = Date.now() - lastAttempt;
  if (timeSinceLastAttempt < STREAM_RECOVERY_DEBOUNCE_MS) {
    log.debug('Recovery debounced', {
      conversationId: convId,
      timeSinceLastAttempt,
      debounceMs: STREAM_RECOVERY_DEBOUNCE_MS,
    });
    return false;
  }

  // For visibility-based recovery, check if hidden long enough
  if (pending.reason === 'visibility') {
    const hiddenDuration = Date.now() - pending.interruptedAt;
    if (hiddenDuration < STREAM_RECOVERY_MIN_HIDDEN_MS) {
      log.debug('Recovery skipped - not hidden long enough', {
        conversationId: convId,
        hiddenDuration,
        minRequired: STREAM_RECOVERY_MIN_HIDDEN_MS,
      });
      clearPendingRecovery(convId);
      return false;
    }
  }

  // Check if recovery is already in progress
  const existingPromise = activeRecoveryPromises.get(convId);
  if (existingPromise) {
    log.debug('Recovery already in progress, waiting', { conversationId: convId });
    return existingPromise;
  }

  // Start recovery
  lastRecoveryAttempt.set(convId, Date.now());
  const recoveryPromise = doRecovery(pending);
  activeRecoveryPromises.set(convId, recoveryPromise);

  try {
    return await recoveryPromise;
  } finally {
    activeRecoveryPromises.delete(convId);
  }
}

// ============ Internal Functions ============

/**
 * Execute the recovery logic with retry.
 */
async function doRecovery(pending: PendingRecovery): Promise<boolean> {
  const { conversationId, expectedMessageId, capturedContent, reason } = pending;

  log.info('Starting recovery', {
    conversationId,
    expectedMessageId,
    reason,
    capturedContentLength: capturedContent.length,
  });

  // Check if this is the current conversation
  const store = useStore.getState();
  const isCurrentConversation = store.currentConversation?.id === conversationId;

  // Show loading toast
  let loadingToast = toast.loading('Recovering response...');

  try {
    // Try to fetch the message with retries
    // The callback updates the toast when entering Phase 2 (content polling)
    const message = await fetchMessageWithRetry(expectedMessageId, () => {
      loadingToast.dismiss();
      loadingToast = toast.loading('Response still being generated...');
    });

    if (message) {
      log.info('Recovery succeeded', {
        conversationId,
        messageId: message.id,
        contentLength: message.content?.length ?? 0,
      });

      // Update UI if this is the current conversation
      if (isCurrentConversation) {
        await updateUIWithRecoveredMessage(conversationId, message);
      }

      // Note: We do NOT call incrementLocalMessageCount here.
      // The caller (cleanupStreamingRequest) handles this when messageSuccessful=true.
      // Incrementing here would cause double-counting (+4 instead of +2).

      // Hide the "new messages available" banner and trigger a sync to re-evaluate.
      // If there are genuinely new messages from another device, the sync will re-show the banner.
      // This handles the race condition where sync showed the banner during recovery.
      if (isCurrentConversation) {
        hideNewMessagesAvailableBanner();
        // Trigger incremental sync to check for genuinely new messages
        getSyncManager()?.incrementalSync();
      }

      loadingToast.dismiss();
      toast.success('Response recovered');
      clearPendingRecovery(conversationId);
      return true;
    } else {
      // Message fetched but no content (incomplete)
      log.warn('Recovery found incomplete message', {
        conversationId,
        messageId: expectedMessageId,
      });

      if (isCurrentConversation) {
        markStreamingMessageAsIncomplete(conversationId);
      }

      loadingToast.dismiss();
      toast.warning('Response may be incomplete');
      clearPendingRecovery(conversationId);
      return false;
    }
  } catch (error) {
    log.error('Recovery failed', { conversationId, error });

    if (isCurrentConversation) {
      markStreamingMessageAsIncomplete(conversationId);
    }

    loadingToast.dismiss();

    // Show error with reload option
    toast.error('Response may be incomplete. Tap to reload.', {
      action: {
        label: 'Reload',
        onClick: () => {
          // Reload the current conversation
          window.location.reload();
        },
      },
    });

    clearPendingRecovery(conversationId);
    return false;
  }
}

/**
 * Check if a message has meaningful content (text, files, or generated images).
 */
function hasContent(message: {
  content: string | null;
  files?: unknown[];
  generated_images?: unknown[];
}): boolean {
  const hasText = !!message.content && message.content.trim() !== '';
  const hasFiles = Array.isArray(message.files) && message.files.length > 0;
  const hasImages = Array.isArray(message.generated_images) && message.generated_images.length > 0;
  return hasText || hasFiles || hasImages;
}

/**
 * Fetch message with two-phase retry:
 *
 * Phase 1 (find): Retry on 404 with exponential backoff. With the placeholder
 * pattern, this succeeds on the first try. Kept as a safety net.
 *
 * Phase 2 (content poll): If the message exists but is empty (placeholder),
 * poll until content appears. This covers long-running agent tool chains
 * (60-120s) where the server hasn't finished processing yet.
 *
 * @param messageId - The expected assistant message ID
 * @param onContentPolling - Callback fired when entering Phase 2
 * @returns Message with content, or null if content never arrived
 */
async function fetchMessageWithRetry(
  messageId: string,
  onContentPolling?: () => void,
): Promise<{ id: string; content: string | null; created_at: string; sources?: unknown[]; generated_images?: unknown[]; files?: unknown[]; language?: string } | null> {
  // Phase 1: Find the message (existing retry logic, should succeed immediately with placeholder)
  type MessageResult = { id: string; content: string | null; created_at: string; sources?: unknown[]; generated_images?: unknown[]; files?: unknown[]; language?: string };
  let message: MessageResult | null = null;

  for (let attempt = 0; attempt <= STREAM_RECOVERY_RETRY_DELAYS_MS.length; attempt++) {
    try {
      message = await conversationsApi.getMessage(messageId);
      break; // Found the message
    } catch (error) {
      const is404 = error instanceof ApiError && error.status === 404;

      if (is404 && attempt < STREAM_RECOVERY_RETRY_DELAYS_MS.length) {
        const delay = STREAM_RECOVERY_RETRY_DELAYS_MS[attempt];
        log.debug('Message not found, retrying', { messageId, attempt, delay });
        await sleep(delay);
        continue;
      }

      // Either not a 404 or we've exhausted retries
      throw error;
    }
  }

  if (!message) {
    throw new ApiError('Message not found after max retries', 404);
  }

  // Check if message already has content
  if (hasContent(message)) {
    return message;
  }

  // Phase 2: Message exists but is empty (placeholder) — poll until content appears
  log.info('Message found but empty (placeholder), polling for content', { messageId });
  onContentPolling?.();

  for (const delay of STREAM_RECOVERY_CONTENT_POLL_DELAYS_MS) {
    await sleep(delay);

    try {
      message = await conversationsApi.getMessage(messageId);
    } catch (error) {
      const is404 = error instanceof ApiError && error.status === 404;
      if (is404) {
        // Message was deleted (user deleted or cleanup) — give up
        log.warn('Message deleted during content polling', { messageId });
        return null;
      }
      throw error;
    }

    if (hasContent(message)) {
      log.info('Content arrived during polling', { messageId });
      return message;
    }
  }

  // Content never arrived
  log.warn('Content polling exhausted, message still empty', { messageId });
  return null;
}

/**
 * Update the UI with the recovered message.
 */
async function updateUIWithRecoveredMessage(
  convId: string,
  message: { id: string; content: string | null; created_at: string; sources?: unknown[]; generated_images?: unknown[]; files?: unknown[]; language?: string }
): Promise<void> {
  // Get the streaming message element
  const messageEl = getStreamingMessageElement(convId);

  if (messageEl && message.content) {
    // Update content
    updateStreamingMessage(messageEl, message.content);

    // Finalize the message
    finalizeStreamingMessage(
      messageEl,
      message.id,
      message.created_at,
      message.sources as Parameters<typeof finalizeStreamingMessage>[3],
      message.generated_images as Parameters<typeof finalizeStreamingMessage>[4],
      message.files as Parameters<typeof finalizeStreamingMessage>[5],
      'assistant',
      message.language
    );

    // Clean up streaming context
    cleanupStreamingContext();

    // Update streaming state
    const store = useStore.getState();
    store.setStreamingConversation(null);
    store.removeActiveRequest(convId);
    getSyncManager()?.setConversationStreaming(convId, false);

    // Update conversation title if it's still "New Conversation"
    const conv = store.currentConversation;
    if (conv && conv.title === 'New Conversation') {
      try {
        const updatedConv = await conversationsApi.get(convId);
        if (updatedConv.title && updatedConv.title !== 'New Conversation') {
          updateConversationTitle(convId, updatedConv.title);
        }
      } catch (error) {
        log.warn('Failed to fetch updated conversation title', { error });
      }
    }

    // Update cost
    await updateConversationCost(convId);
  } else if (!messageEl && message.content) {
    // No streaming context, but there might still be a streaming/incomplete element in the DOM
    // This happens when the context was cleaned up but the DOM element remains
    const container = getElementById<HTMLDivElement>('messages');
    if (container) {
      // Try to find the element by ID first (most reliable), then fall back to class selectors
      // The ID is set on the streaming element when we receive expected_assistant_message_id
      const existingEl = (
        container.querySelector(`[data-message-id="${message.id}"]`) ||
        container.querySelector('.message.assistant.streaming, .message.assistant.message-incomplete')
      ) as HTMLElement | null;

      if (existingEl) {
        // Found existing element - update it in place
        log.info('Found orphaned streaming element, updating in place', { conversationId: convId });

        // Update the content
        updateStreamingMessage(existingEl, message.content);

        // Finalize it properly
        finalizeStreamingMessage(
          existingEl,
          message.id,
          message.created_at,
          message.sources as Parameters<typeof finalizeStreamingMessage>[3],
          message.generated_images as Parameters<typeof finalizeStreamingMessage>[4],
          message.files as Parameters<typeof finalizeStreamingMessage>[5],
          'assistant',
          message.language
        );
      } else {
        // No existing element found - add new message
        log.info('No streaming element in DOM, adding recovered message', { conversationId: convId });

        const messageObj: Message = {
          id: message.id,
          role: 'assistant',
          content: message.content,
          created_at: message.created_at,
          sources: message.sources as Source[] | undefined,
          generated_images: message.generated_images as GeneratedImage[] | undefined,
          files: message.files as FileMetadata[] | undefined,
          language: message.language,
        };

        addMessageToUI(messageObj, container);

        // Also update the store's messages
        const store = useStore.getState();
        store.appendMessage(convId, messageObj);
      }

      // Scroll to show the message
      scrollToBottom(container);

      // Clean up streaming state
      cleanupStreamingContext();
      const store = useStore.getState();
      store.setStreamingConversation(null);
      store.removeActiveRequest(convId);
      getSyncManager()?.setConversationStreaming(convId, false);

      // Update conversation title if it's still "New Conversation"
      const conv = store.currentConversation;
      if (conv && conv.title === 'New Conversation') {
        try {
          const updatedConv = await conversationsApi.get(convId);
          if (updatedConv.title && updatedConv.title !== 'New Conversation') {
            updateConversationTitle(convId, updatedConv.title);
          }
        } catch (error) {
          log.warn('Failed to fetch updated conversation title', { error });
        }
      }

      // Update cost
      await updateConversationCost(convId);
    }
  }
}

/**
 * Mark the streaming message as incomplete.
 */
function markStreamingMessageAsIncomplete(convId: string): void {
  const messageEl = getStreamingMessageElement(convId);
  if (messageEl) {
    messageEl.classList.add('message-incomplete');
    // Remove streaming class and cursor
    messageEl.classList.remove('streaming');
    const cursor = messageEl.querySelector('.streaming-cursor');
    cursor?.remove();
  }

  // Clean up streaming state
  cleanupStreamingContext();
  const store = useStore.getState();
  store.setStreamingConversation(null);
  store.removeActiveRequest(convId);
  getSyncManager()?.setConversationStreaming(convId, false);
}

/**
 * Sleep utility.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
