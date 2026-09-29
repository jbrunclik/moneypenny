/**
 * Completion of a streamed turn: the terminal `done` event finalizes the
 * streaming bubble, records the reply in the store and settles scroll,
 * title and cost.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import {
  appendStoppedEarlyNote,
  updateStreamingMessage,
  finalizeStreamingMessage,
  getStreamingMessageElement,
  updateUserMessageId,
} from '../components/messages';
import { getElementById } from '../utils/dom';
import type { FileMetadata, GeneratedImage, Message, Source } from '../types/api';
import { updateConversationTitle } from './conversation-actions';
import { updateConversationCost } from './toolbar';
import { clearPendingRecovery } from './stream-recovery';
import type { StreamingState } from './stream-session';
import { handleImageScrollAfterMessage, scrollToFinishedStreamMessage } from './response-scroll';

const log = createLogger('messaging');

/** Payload of the stream's terminal `done` event (the saved assistant message). */
export interface StreamDoneEvent {
  id: string;
  created_at: string;
  content?: string;
  user_message_id?: string;
  sources?: Source[];
  generated_images?: GeneratedImage[];
  files?: FileMetadata[];
  title?: string;
  language?: string;
  approval_required?: boolean;
  approval_id?: string;
  stopped_early?: boolean;
}

/**
 * The store Message for a completed streamed reply - the same data the
 * finalized bubble renders. The server's saved content wins; the streamed
 * text covers a done event that carries none.
 */
export function assistantMessageFromDone(event: StreamDoneEvent, streamedContent: string): Message {
  return {
    id: event.id,
    role: 'assistant',
    content: event.content || streamedContent,
    created_at: event.created_at,
    sources: event.sources,
    generated_images: event.generated_images,
    files: event.files,
    language: event.language,
    stopped_early: event.stopped_early,
  };
}

/** Whether the done event has anything to show (not just metadata-only tool calls). */
export function hasVisibleContent(event: StreamDoneEvent): boolean {
  return Boolean(
    event.content?.trim() ||
    event.files?.length || event.generated_images?.length || event.sources?.length
  );
}

/**
 * The user switched away mid-stream: the turn still completed - do the
 * bookkeeping without touching the (re-rendered) DOM. Bailing before
 * messageSuccessful left every backgrounded stream looking interrupted,
 * triggering a pointless recovery round and a wrong local message count.
 */
function completeInBackground(event: StreamDoneEvent, state: StreamingState, convId: string): void {
  state.messageSuccessful = true;
  clearPendingRecovery(convId);
  useStore.getState().appendMessage(convId, assistantMessageFromDone(event, state.fullContent));
  if (event.title) {
    updateConversationTitle(convId, event.title);
  }
}

/**
 * Finalize the streaming bubble with the saved message. Returns whether the
 * user was following the stream (at the bottom) when it finished.
 */
function finalizeDoneBubble(
  event: StreamDoneEvent,
  state: StreamingState,
  convId: string,
  messageEl: HTMLElement
): boolean {
  // Recovery: If tokens weren't rendered during streaming but done event has content,
  // render the content now. This handles cases where SSE token events were lost
  // (e.g., connection issues, iOS Safari quirks) but the done event arrived.
  if (event.content && !state.fullContent.trim()) {
    log.warn('Recovering content from done event - tokens were not streamed', {
      conversationId: convId,
      contentLength: event.content.length,
    });
    // Render the content that should have been streamed
    updateStreamingMessage(messageEl, event.content);
  }

  const wasFollowing = finalizeStreamingMessage(
    messageEl,
    event.id,
    event.created_at,
    event.sources,
    event.generated_images,
    event.files,
    'assistant',
    event.language
  );
  useStore.getState().appendMessage(convId, assistantMessageFromDone(event, state.fullContent));
  if (event.stopped_early) {
    const wrapper = messageEl.querySelector<HTMLElement>('.message-content-wrapper');
    if (wrapper) appendStoppedEarlyNote(wrapper, event.id);
  }
  return wasFollowing;
}

/**
 * Scroll to top of message if user was following, otherwise handle image scroll.
 */
function scrollAfterDone(event: StreamDoneEvent, messageEl: HTMLElement, wasFollowing: boolean): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  log.info('Streaming done scroll decision', {
    wasFollowing,
    hasMessagesContainer: !!messagesContainer,
    messageElOffsetTop: messageEl.offsetTop,
  });

  if (wasFollowing && messagesContainer) {
    // User was following the stream - scroll to top of the assistant's response
    scrollToFinishedStreamMessage(messagesContainer, messageEl);
  } else {
    // User scrolled away during streaming - don't auto-scroll, just handle images
    log.info('Not scrolling to top - user scrolled away or no container');
    handleImageScrollAfterMessage(messageEl, event.files);
  }
}

/**
 * Handle stream done event.
 */
export async function handleStreamDone(
  event: StreamDoneEvent,
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): Promise<void> {
  log.info('Streaming complete', {
    conversationId: convId,
    messageId: event.id,
    approvalRequired: event.approval_required,
    hasContent: !!event.content,
    streamedContentLength: state.fullContent.length,
  });

  if (event.user_message_id) {
    updateUserMessageId(tempUserMessageId, event.user_message_id);
  }

  const isCurrentConversation = useStore.getState().currentConversation?.id === convId;
  if (!isCurrentConversation) {
    completeInBackground(event, state, convId);
    return;
  }

  // Get the current streaming element from context, which may have been restored
  // when switching back to this conversation. If the context doesn't exist or
  // doesn't match this conversation, fall back to the original element.
  const messageEl = getStreamingMessageElement(convId) ?? state.messageEl;

  // If the done event has no visible content (e.g. metadata-only tool calls),
  // remove the empty message element instead of leaving an empty bubble
  if (!hasVisibleContent(event)) {
    messageEl.remove();
    clearPendingRecovery(convId);
    state.messageSuccessful = true;
    await updateConversationCost(convId);
    return;
  }

  const wasFollowing = finalizeDoneBubble(event, state, convId, messageEl);
  scrollAfterDone(event, messageEl, wasFollowing);

  updateConversationTitle(convId, event.title);
  // Same window as the batch path: the stream is done, so a follow-up sent
  // while the cost fetch is in flight must start a new turn, not interject
  useStore.getState().removeActiveRequest(convId);
  await updateConversationCost(convId);

  // If approval was requested, the message element will contain the approval buttons
  // The frontend rendering handles approval_request markers automatically
  if (event.approval_required) {
    log.info('Message finalized with pending approval', {
      conversationId: convId,
      approvalId: event.approval_id,
    });
  }

  // Clear any pending recovery since stream completed successfully
  clearPendingRecovery(convId);

  state.messageSuccessful = true;
}
