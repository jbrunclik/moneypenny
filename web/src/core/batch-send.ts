/**
 * Batch (non-streaming) send: one request, one complete assistant reply.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { chat } from '../api/chat';
import { ApiError } from '../api/http';
import {
  addMessageToUI,
  showLoadingIndicator,
  hideLoadingIndicator,
  updateUserMessageId,
} from '../components/messages';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { renderResearchOffer } from '../components/messages/research-offer';
import {
  showUploadProgress,
  hideUploadProgress,
  updateUploadProgress,
} from '../components/MessageInput';
import { getElementById, isScrolledToBottom } from '../utils/dom';
import type { ChatResponse, ClientLocation, FileUpload, Message, SendExtras } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';
import { updateConversationTitle } from './conversation-actions';
import { updateConversationCost } from './toolbar';
import { notifyTurnFinished } from './attention';
import { trackRequest, untrackRequest } from './active-requests';
import { confirmDelivery, markSendFailed } from './send-delivery';
import { scrollToBatchReply, settleAnchoredReply } from './response-scroll';
import { isTurnAnchored, reserveTurnSpace } from '../components/messages/turn-anchor';
import { notifyModelFallback } from './model-fallback';
import { clearInflightBatch, persistInflightBatch } from './batch-resume';

const log = createLogger('messaging');

function hideBatchProgress(): void {
  hideLoadingIndicator();
  hideUploadProgress();
  useStore.getState().setUploadProgress(null);
}

/** Track the request and show upload progress or the loading indicator. */
function beginBatchRequest(convId: string, requestId: string, hasFiles: boolean): void {
  // Like a stream: a poll mid-turn sees our own user message, which must not
  // read as an external update (deferred until the turn ends)
  getSyncManager()?.setConversationStreaming(convId, true);
  trackRequest(requestId, {
    conversationId: convId,
    type: 'batch',
  });

  // Register active request in store for UI restoration on conversation switch
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'batch',
  });

  // Show upload progress for requests with files
  if (hasFiles) {
    showUploadProgress();
  } else {
    showLoadingIndicator();
  }
}

function toAssistantMessage(response: ChatResponse): Message {
  return {
    id: response.id,
    role: 'assistant',
    content: response.content,
    sources: response.sources,
    generated_images: response.generated_images,
    files: response.files,
    language: response.language,
    created_at: response.created_at,
    stopped_early: response.stopped_early,
    annotations: response.annotations,
    grounding: response.grounding,
    research: response.research,
  };
}

/** Render the reply and scroll to it if the user was following. */
function renderBatchReply(assistantMessage: Message): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;

  const hasImagesToLoad = assistantMessage.files?.some(
    (f) => f.type.startsWith('image/') && !f.previewUrl
  ) ?? false;

  // Send-to-top: the reply takes over the loader's reserved space in this
  // same task (before any layout read would clamp the position) and the
  // view stays on the turn
  if (isTurnAnchored()) {
    addMessageToUI(assistantMessage, messagesContainer, undefined, { animate: true });
    const replyEl = messagesContainer.querySelector<HTMLElement>(`[data-message-id="${assistantMessage.id}"]`);
    if (replyEl) {
      reserveTurnSpace(messagesContainer, replyEl);
      if (assistantMessage.research) renderResearchOffer(replyEl, assistantMessage, { live: true });
      settleAnchoredReply(messagesContainer, replyEl);
    }
    return;
  }

  const wasAtBottom = isScrolledToBottom(messagesContainer);
  // Note: We intentionally don't call enableScrollOnImageLoad() here because
  // we're using scroll-to-top-of-message behavior, not scroll-to-bottom.
  // The scroll-on-image-load system is designed for bottom-scrolling.
  addMessageToUI(assistantMessage, messagesContainer, undefined, { animate: true });
  // A reply that just arrived: an autostart offer starts now
  const messageEl = messagesContainer.querySelector<HTMLElement>(`[data-message-id="${assistantMessage.id}"]`);
  if (messageEl && assistantMessage.research) renderResearchOffer(messageEl, assistantMessage, { live: true });

  // Only scroll if user was following (at bottom) - don't hijack scroll if user is browsing history
  if (wasAtBottom) {
    scrollToBatchReply(messagesContainer, assistantMessage.id, hasImagesToLoad);
  } else {
    // User is browsing history - just update scroll button visibility
    requestAnimationFrame(() => {
      checkScrollButtonVisibility();
    });
  }
}

/** A reply arrived: record it, render it (if visible) and settle bookkeeping. */
async function completeBatchTurn(
  convId: string,
  tempUserMessageId: string,
  response: ChatResponse
): Promise<void> {
  // Response received = the user message is persisted server-side
  confirmDelivery(convId, tempUserMessageId);
  if (response.model_fallback && useStore.getState().currentConversation?.id === convId) {
    notifyModelFallback(response.model_fallback);
  }

  // Update user message ID from temp to real ID (for file fetching in lightbox)
  if (response.user_message_id) {
    updateUserMessageId(tempUserMessageId, response.user_message_id);
  }

  // The sync baseline first (the server's exact count), even if the user
  // switched away - returning before it left our own turn as "unread 2"
  const sync = getSyncManager();
  if (response.message_count !== undefined) {
    sync?.setLocalMessageCount(convId, response.message_count);
  } else {
    sync?.incrementLocalMessageCount(convId, 2);
  }
  sync?.setConversationStreaming(convId, false);

  const assistantMessage = toAssistantMessage(response);
  // The store is authoritative for the conversation's messages - record
  // the reply whether or not it gets rendered below
  useStore.getState().appendMessage(convId, assistantMessage);

  hideBatchProgress();
  // Check if conversation is still current before updating UI
  if (useStore.getState().currentConversation?.id !== convId) {
    // User switched conversations - message is saved to DB, just hide loading
    return;
  }

  renderBatchReply(assistantMessage);

  // Update conversation title if this was the first message (title comes from response)
  updateConversationTitle(convId, response.title);

  // Update conversation cost
  await updateConversationCost(convId);

  notifyTurnFinished();
}

/**
 * Send message with batch response.
 */
export async function sendBatchMessage(
  convId: string,
  message: string,
  files: FileUpload[],
  forceTools: string[],
  tempUserMessageId: string,
  anonymousMode: boolean,
  clientLocation: ClientLocation | null | Promise<ClientLocation | null> = null,
  rerunMode?: 'regenerate' | 'continue',
  extras: SendExtras = {}
): Promise<void> {
  const requestId = `batch-${convId}-${Date.now()}`;
  const hasFiles = files && files.length > 0;
  beginBatchRequest(convId, requestId, hasFiles);
  // Survives the page: a reload mid-turn waits for this message's reply
  if (!rerunMode) persistInflightBatch(convId, tempUserMessageId);

  try {
    // Pass progress callback for requests with files
    const onUploadProgress = hasFiles ? (progress: number) => {
      updateUploadProgress(progress);
      useStore.getState().setUploadProgress(progress);
    } : undefined;

    // Awaited after the loading indicator is up (beginBatchRequest)
    const location = await clientLocation;
    const response = await chat.sendBatch(convId, message, files, forceTools, onUploadProgress, anonymousMode, location, rerunMode ? undefined : tempUserMessageId, rerunMode, extras);
    log.info('Batch response received', { conversationId: convId, messageId: response.id });

    // The turn is over the moment the response is in: release the active
    // request NOW, not in the finally after the cost/title bookkeeping below.
    // While it stayed set, a message sent in that window (a fast follow-up,
    // or an E2E loop) was routed to /chat/interject - queued into a turn that
    // had already finished, so it was stored but never answered.
    untrackRequest(requestId);
    useStore.getState().removeActiveRequest(convId);
    clearInflightBatch(convId, tempUserMessageId);

    await completeBatchTurn(convId, tempUserMessageId, response);
  } catch (error) {
    hideBatchProgress();
    // A dropped connection may be the page going away (reload, iOS killing
    // the PWA) - the fetch rejects before unload. Keep the entry for the next
    // load; it reconciles against the server either way.
    const dropped = error instanceof ApiError && (error.isNetworkError || error.isTimeout);
    if (!dropped) clearInflightBatch(convId, tempUserMessageId);

    // 409 = delivered by a previous attempt; propagate for reconciliation
    if (error instanceof ApiError && error.status === 409) {
      throw error;
    }

    // Check if conversation is still current before showing errors
    if (useStore.getState().currentConversation?.id !== convId) {
      // User switched conversations - swallow the error but record the
      // failure so the outbox doesn't lose track of it
      markSendFailed(convId, tempUserMessageId);
      return;
    }

    // Propagate: handleSendFailure decides between auto-retry and failed state
    throw error;
  } finally {
    // A failed turn ends here too (no-op after completeBatchTurn)
    getSyncManager()?.setConversationStreaming(convId, false);
    // Clean up request tracking
    untrackRequest(requestId);
    // Remove active request from store
    useStore.getState().removeActiveRequest(convId);
    // Ensure upload progress is hidden (safety net)
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);
  }
}
