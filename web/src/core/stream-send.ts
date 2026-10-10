/**
 * Streaming send: runs one turn over SSE, from the request through the
 * event loop to resume/recovery when the reader dies.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { chat } from '../api/chat';
import { ApiError } from '../api/http';
import { toast } from '../components/Toast';
import { hideUploadProgress } from '../components/MessageInput';
import type { ClientLocation, FileUpload, SendExtras, StreamEvent } from '../types/api';
import { setStopHandler } from './active-requests';
import { clearInflightStream } from './inflight-streams';
import { confirmDelivery, markSendFailed } from './send-delivery';
import { markStreamForRecovery, clearPendingRecovery, attemptRecovery } from './stream-recovery';
import { handleStreamDone, type StreamDoneEvent } from './stream-done';
import { processStreamEvent } from './stream-events';
import { mergeExternalChanges } from './remote-merge';
import { handleMissingDoneEvent, tryResumeStream } from './stream-resume';
import {
  cleanupStreamingRequest,
  initStreamingRequest,
  requestServerStop,
  setupStreamLifecycleListeners,
  type StreamingState,
} from './stream-session';

const log = createLogger('messaging');

/** Everything one streaming send needs, threaded through the helpers below. */
interface StreamSend {
  convId: string;
  tempUserMessageId: string;
  hasFiles: boolean;
  state: StreamingState;
}

/**
 * Toggle the uploading state on the optimistic user message so its
 * attachment chips can indicate the in-flight upload.
 */
function setUserMessageUploading(tempUserMessageId: string, uploading: boolean): void {
  const el = document.querySelector(`.message.user[data-message-id="${tempUserMessageId}"]`);
  el?.classList.toggle('uploading', uploading);
}

/**
 * Hide upload progress, reveal the assistant bubble, clear the user
 * bubble's upload state.
 */
function revealAfterUpload(send: StreamSend): void {
  if (!send.hasFiles || send.state.uploadProgressHidden) return;
  hideUploadProgress();
  useStore.getState().setUploadProgress(null);
  send.state.uploadProgressHidden = true;
  send.state.messageEl.classList.remove('awaiting-upload');
  setUserMessageUploading(send.tempUserMessageId, false);
}

/** Drain the live stream, dispatching each event. */
async function consumeStream(send: StreamSend, events: AsyncGenerator<StreamEvent>): Promise<void> {
  const { convId, tempUserMessageId, state } = send;
  let deliveryConfirmed = false;

  for await (const event of events) {
    // First event = server has the message: the send can no longer fail
    if (!deliveryConfirmed) {
      deliveryConfirmed = true;
      confirmDelivery(convId, tempUserMessageId);
    }

    revealAfterUpload(send);

    // Track the journal seq so an interrupted stream can resume from offset
    if (typeof event.seq === 'number') {
      state.lastSeq = event.seq;
    }

    // Handle done event specially (async)
    if (event.type === 'done') {
      await handleStreamDone(event as unknown as StreamDoneEvent, state, convId, tempUserMessageId);
      continue;
    }

    // Another device's turn was running: the server saved this send as
    // steering for it - no reply of our own; follow that one instead
    if (event.type === 'interjected') {
      state.interjectedInto = event.message_id;
      state.serverMessageCount = event.message_count;
      state.messageEl.remove();
      return;
    }

    // Server-side CHAT_TIMEOUT: partial content was saved; let the loop
    // drain and the missing-done path recover the saved message
    if (event.type === 'timeout') {
      log.warn('Stream timed out server-side', { conversationId: convId });
      toast.warning('Response timed out. Recovering saved content...');
      continue;
    }

    // Process other events
    const result = processStreamEvent(event, state, convId, tempUserMessageId);
    if (result.error) {
      throw result.error;
    }
  }
}

/** The user stopped the stream (initial reader or a resume): terminal. */
function handleUserStop(send: StreamSend, logMessage: string): void {
  log.info(logMessage, { conversationId: send.convId });
  send.state.messageEl.remove();
  toast.info('Response stopped.');
  // Clear any pending recovery since this was user-initiated
  clearPendingRecovery(send.convId);
}

/**
 * Attempt resume/recovery for network/timeout errors if we have an expected
 * message ID. Returns 'delivered' when the reply was recovered, 'stopped'
 * when the user stopped it meanwhile, 'failed' otherwise.
 */
async function recoverAfterStreamError(
  send: StreamSend,
  error: unknown
): Promise<'delivered' | 'stopped' | 'failed'> {
  const { convId, tempUserMessageId, state } = send;
  if (!state.expectedAssistantMessageId) return 'failed';

  // Resume from the journal first: replays missed events and continues live
  // (resumeViaAbort stays set on a proactive abort: tryResumeStream uses it
  // to tell the aborted main reader apart from a user stop)
  let resumed: boolean;
  try {
    resumed = await tryResumeStream(state, convId, tempUserMessageId);
  } catch (resumeError) {
    if (resumeError instanceof Error && resumeError.name === 'AbortError') {
      // User stopped the stream while a resume was in flight
      handleUserStop(send, 'Resume aborted by user');
      return 'stopped';
    }
    throw resumeError;
  }
  if (resumed) return 'delivered';

  const reason = (error instanceof ApiError && error.isTimeout) ? 'timeout' : 'network';
  markStreamForRecovery(convId, state.expectedAssistantMessageId, state.fullContent, reason);

  // Attempt recovery immediately for non-visibility errors. Success means
  // no error shown and nothing thrown (messageSuccessful keeps the local
  // message count in sync - R11)
  const recovered = await attemptRecovery(convId);
  return recovered ? 'delivered' : 'failed';
}

/**
 * The stream failed: stop, resume/recover, or surface the error. Throws when
 * the dispatch level must decide (409 reconcile, auto-retry, failed state).
 */
async function handleStreamFailure(send: StreamSend, error: unknown): Promise<void> {
  const { convId, tempUserMessageId, state } = send;
  if (error instanceof Error && error.name === 'AbortError' && !state.resumeViaAbort) {
    if (state.stopRequested) {
      // Server-side stop whose done event never arrived in time: the partial
      // is (or will be) saved - keep the bubble; sync replaces it later
      state.messageEl.classList.add('message-incomplete');
      toast.info('Response stopped.');
      clearPendingRecovery(convId);
      return;
    }
    // Stopped before the server confirmed receipt: surface as a failed
    // send (retry-able); reconciliation resolves it if it actually landed
    markSendFailed(convId, tempUserMessageId);
    handleUserStop(send, 'Stream aborted by user');
    return;
  }
  log.error('Streaming failed', { error, conversationId: convId });

  const recovery = await recoverAfterStreamError(send, error);
  if (recovery === 'stopped') return;
  if (recovery === 'delivered') {
    state.messageSuccessful = true;
    return;
  }

  // Recovery failed or not possible - show error state
  if (state.fullContent.trim()) {
    state.messageEl.classList.add('message-incomplete');
  } else {
    state.messageEl.remove();
  }

  // 409 means the message actually landed on a previous attempt - always
  // propagate so the dispatch level reconciles instead of marking failed
  if (error instanceof ApiError && error.status === 409) {
    throw error;
  }

  const isCurrentConversation = useStore.getState().currentConversation?.id === convId;
  if (isCurrentConversation) {
    // Propagate: handleSendFailure decides between a silent auto-retry and
    // the failed state. Marking failed HERE flashed the retry/discard
    // buttons for the 2s auto-retry window.
    throw error;
  }

  // Swallowed (user switched away): record the failure so the outbox
  // doesn't lose track of it
  markSendFailed(convId, tempUserMessageId);
}

/**
 * Send message with streaming response.
 */
export async function sendStreamingMessage(
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
  const hasFiles = files && files.length > 0;
  // The thinking bar goes up before anything is awaited (the location fix)
  const { state, requestId, abortController } = initStreamingRequest(convId, hasFiles);
  if (hasFiles) {
    setUserMessageUploading(tempUserMessageId, true);
  }
  const send: StreamSend = { convId, tempUserMessageId, hasFiles, state };
  setStopHandler(convId, () => requestServerStop(convId, state));

  // Mark for recovery on mobile background/lock; proactively resume on return
  const cleanupLifecycleListeners = setupStreamLifecycleListeners(state, convId);

  try {
    const location = await clientLocation;
    await consumeStream(send, chat.stream(convId, message, files, forceTools, abortController, anonymousMode, location, rerunMode ? undefined : tempUserMessageId, rerunMode, extras));

    // Handle stream ending without done event (connection dropped mid-stream)
    // The message may have been saved server-side, so try to recover it
    if (!state.messageSuccessful && !state.interjectedInto) {
      log.warn('Stream ended without done event', {
        conversationId: convId,
        hadContent: state.fullContent.trim() !== '',
      });
      await handleMissingDoneEvent(state, convId, tempUserMessageId);
    }
  } catch (error) {
    await handleStreamFailure(send, error);
  } finally {
    if (state.stopTimer) clearTimeout(state.stopTimer);
    cleanupLifecycleListeners();
    // Safety net: never leave the user bubble pulsing or the assistant
    // bubble hidden if the request died before the first event
    if (hasFiles) {
      setUserMessageUploading(tempUserMessageId, false);
      state.messageEl.classList.remove('awaiting-upload');
    }
    // The turn finished (or its failure was surfaced) in this page - only a
    // page that died mid-stream should resume after reload. Per-conversation:
    // other concurrent streams keep their entries.
    clearInflightStream(convId);
    cleanupStreamingRequest(requestId, convId, state.messageSuccessful, state.serverMessageCount);
  }
  // (after the cleanup: a merge skips a conversation with a turn of its own)
  // Renders the other device's question in place and follows its reply live
  if (state.interjectedInto) await mergeExternalChanges(convId);
}
