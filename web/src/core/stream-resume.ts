/**
 * Resumable streams, client side: reconnect to the server's stream journal
 * after the reader dropped (network handoff, iOS background stint) or after
 * the page itself died mid-turn (reload), falling back to poll recovery.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { chat } from '../api/client';
import { ApiError } from '../api/http';
import { toast } from '../components/Toast';
import { addStreamingMessage, getStreamingMessageElement } from '../components/messages';
import { getElementById } from '../utils/dom';
import { getSyncManager } from '../sync/SyncManager';
import { swapAbortController } from './active-requests';
import { clearInflightStream, readInflightStream } from './inflight-streams';
import { markStreamForRecovery, clearPendingRecovery, attemptRecovery } from './stream-recovery';
import { handleStreamDone, type StreamDoneEvent } from './stream-done';
import { processStreamEvent } from './stream-events';
import {
  cleanupStreamingRequest,
  createStreamingState,
  registerStreamRequest,
  setupStreamLifecycleListeners,
  type StreamingState,
} from './stream-session';

const log = createLogger('messaging');

const MAX_RESUME_ATTEMPTS = 3;

/**
 * Read one resume stream to its end. Returns true when the turn completed
 * (done), false when it is not resumable, null when the stream ended
 * without a verdict (retry - the save may still be in flight).
 */
async function readResumeStream(
  state: StreamingState,
  convId: string,
  messageId: string,
  controller: AbortController,
  tempUserMessageId: string
): Promise<boolean | null> {
  for await (const event of chat.resumeStream(convId, messageId, state.lastSeq, controller)) {
    if (typeof event.seq === 'number') {
      state.lastSeq = event.seq;
    }
    if (event.type === 'done') {
      await handleStreamDone(event as unknown as StreamDoneEvent, state, convId, tempUserMessageId);
      return true;
    }
    if (event.type === 'error') {
      if (event.code === 'RESUME_FAILED') {
        // Turn failed server-side and nothing was saved - not retryable
        return false;
      }
      throw new Error(event.message);
    }
    if (event.type === 'timeout') {
      // The resume endpoint exhausted its own deadline - the turn is
      // dead; retrying the resume cannot help. Fall back to poll recovery.
      log.warn('Resume timed out server-side', { conversationId: convId });
      return false;
    }
    const result = processStreamEvent(event, state, convId, tempUserMessageId);
    if (result.error) {
      throw result.error;
    }
  }
  return null;
}

/**
 * Handle stream ending without a done event.
 * This can happen if the connection drops mid-stream but the server still saves the message.
 * Uses the stream recovery module which handles retries for race conditions.
 *
 * Throws AbortError when the user stops the stream mid-resume; a proactive
 * (foreground/pageshow) abort retries from the journal offset instead.
 */
export async function tryResumeStream(
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): Promise<boolean> {
  if (!state.expectedAssistantMessageId) return false;
  const messageId = state.expectedAssistantMessageId;

  for (let attempt = 0; attempt < MAX_RESUME_ATTEMPTS; attempt++) {
    // An aborted controller at this point is either the user stopping the
    // stream (during the backoff sleep, or the pre-resume reader) or the
    // proactive bg/fg abort that brought us here - resumeViaAbort tells apart
    if (state.activeAbortController?.signal.aborted && !state.resumeViaAbort) {
      throw new DOMException('Aborted', 'AbortError');
    }
    state.resumeViaAbort = false;

    // Fresh reader, fresh controller - swap it into the tracked request so
    // the stop button and the bg/fg abort target the reader that is live
    const controller = new AbortController();
    state.activeAbortController = controller;
    swapAbortController(convId, controller);

    try {
      log.info('Attempting stream resume', {
        conversationId: convId,
        messageId,
        afterSeq: state.lastSeq,
        attempt,
      });
      clearPendingRecovery(convId);
      const outcome = await readResumeStream(state, convId, messageId, controller, tempUserMessageId);
      if (outcome !== null) return outcome;
      // Stream ended without done - retry (the save may still be in flight)
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        if (state.resumeViaAbort) {
          // Foregrounded mid-resume: this reader is presumed dead - retry
          // immediately from the journal offset (flag reset at loop top)
          continue;
        }
        throw error; // User-initiated stop - propagate to the caller
      }
      // 404 = no journal for this message (expired, or server without the
      // endpoint) - fall back to poll-based recovery immediately
      if (error instanceof ApiError && error.status === 404) {
        log.info('Resume endpoint has no journal, falling back', { conversationId: convId });
        return false;
      }
      log.warn('Stream resume attempt failed', { error, conversationId: convId, attempt });
    }
    if (attempt < MAX_RESUME_ATTEMPTS - 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)));
    }
  }
  return false;
}

/**
 * The live stream ended without a done event: resume from the journal, then
 * fall back to poll recovery.
 */
export async function handleMissingDoneEvent(
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): Promise<void> {
  const isCurrentConversation = useStore.getState().currentConversation?.id === convId;
  if (!isCurrentConversation) {
    // User switched away - just clean up the streaming element
    state.messageEl.remove();
    return;
  }

  // If we don't have the expected message ID, we can't reliably recover
  if (!state.expectedAssistantMessageId) {
    log.warn('Cannot recover - no expected assistant message ID', {
      conversationId: convId,
    });
    if (state.fullContent.trim()) {
      state.messageEl.classList.add('message-incomplete');
    } else {
      state.messageEl.remove();
    }
    return;
  }

  // Resume from the journal first: replays missed events and continues live
  const resumed = await tryResumeStream(state, convId, tempUserMessageId);
  if (resumed) {
    state.messageSuccessful = true;
    return;
  }

  // Fall back to the poll-based recovery module (handles journal-expired cases)
  markStreamForRecovery(convId, state.expectedAssistantMessageId, state.fullContent, 'network');
  const recovered = await attemptRecovery(convId);

  if (recovered) {
    state.messageSuccessful = true;
  }
  // If not recovered, the recovery module already handled showing error UI
}

/**
 * Find the message this conversation was streaming when the page died.
 * Returns null (clearing a stale entry) when there is nothing to resume.
 */
function findResumableMessage(convId: string): { messageId: string; placeholder: Element | null } | null {
  const entry = readInflightStream(convId);
  if (!entry) return null;

  const container = getElementById<HTMLDivElement>('messages');
  const existing = container?.querySelector(`[data-message-id="${entry.messageId}"]`) ?? null;
  // Check the CONTENT element, not the whole bubble - an empty placeholder
  // still has timestamps/action buttons in its textContent
  const existingContent = existing?.querySelector('.message-content')?.textContent ?? '';
  if (existing && existingContent.trim() !== '') {
    // The turn completed before the reload; the saved message is rendered
    clearInflightStream(convId);
    return null;
  }
  return { messageId: entry.messageId, placeholder: existing };
}

/**
 * Resume the journal for a reloaded turn, falling back to poll recovery.
 * Returns whether the reply was delivered, or 'stopped' when the user
 * stopped it mid-resume.
 */
async function deliverResumedTurn(
  state: StreamingState,
  convId: string,
  messageId: string,
  messageEl: HTMLElement
): Promise<boolean | 'stopped'> {
  let delivered: boolean;
  try {
    delivered = await tryResumeStream(state, convId, '');
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      // User stopped the resumed turn - terminal, no recovery
      log.info('Reload-resume aborted by user', { conversationId: convId });
      (getStreamingMessageElement(convId) ?? messageEl).remove();
      toast.info('Response stopped.');
      clearPendingRecovery(convId);
      return 'stopped';
    }
    throw error;
  }
  if (delivered) return true;
  // Journal gone or turn dead - poll recovery handles saved-but-swept
  markStreamForRecovery(convId, messageId, '', 'network');
  delivered = await attemptRecovery(convId);
  if (!delivered) {
    messageEl.remove();
  }
  return delivered;
}

/**
 * Resume an in-flight stream after a page crash/reload.
 *
 * Called when a conversation's messages finish rendering. If localStorage
 * holds a fresh in-flight entry for THIS conversation and the assistant
 * message is still empty (the turn was mid-flight when the page died),
 * replays the journal from seq 0 - there is no rendered prefix to offset
 * from - and continues live.
 */
export async function resumeInflightStreamIfAny(convId: string): Promise<void> {
  // The stream is still live in THIS tab (conversation switch, not a reload):
  // the activeRequest restore path re-creates the streaming UI and the live
  // reader keeps feeding it. Resuming here would spawn a second, competing
  // reader and a duplicate bubble - and consume the entry a real reload needs.
  if (useStore.getState().getActiveRequest(convId)) return;
  const resumable = findResumableMessage(convId);
  if (!resumable) return;
  const { messageId, placeholder } = resumable;

  log.info('Resuming in-flight stream after reload', { conversationId: convId, messageId });

  // Replace the empty placeholder bubble (if the loader rendered it) with a
  // live streaming bubble
  if (placeholder instanceof HTMLElement) {
    placeholder.remove();
  }
  const messageEl = addStreamingMessage(convId);
  messageEl.dataset.messageId = messageId;

  // One controller shared between the tracked request and the state so a
  // stop click in the window before the first resume attempt is not lost
  const abortController = new AbortController();
  const state = createStreamingState(messageEl, {
    uploadProgressHidden: true,
    expectedAssistantMessageId: messageId,
    activeAbortController: abortController,
  });

  // Register in the store too: the getActiveRequest guard above blocks
  // re-entry from further conversation switches, and the switch-back restore
  // path can re-create this bubble with the accumulated content
  const requestId = `resume-${convId}-${Date.now()}`;
  registerStreamRequest(convId, requestId, abortController);

  // Same bg/fg handling as a live stream: the resume reader can die in an
  // iOS background stint too
  const cleanupLifecycleListeners = setupStreamLifecycleListeners(state, convId);

  let delivered = false;
  try {
    delivered = (await deliverResumedTurn(state, convId, messageId, messageEl)) === true;
  } finally {
    cleanupLifecycleListeners();
    // The localStorage entry survives until HERE (terminal outcome): clearing
    // it up front meant a second reload mid-resume found nothing and silently
    // abandoned the still-running turn
    clearInflightStream(convId);
    // messageSuccessful=false on purpose: the reload refetched server counts,
    // so the user message is already counted - only the newly delivered
    // assistant message needs the local baseline bump
    cleanupStreamingRequest(requestId, convId, false);
    if (delivered) {
      getSyncManager()?.incrementLocalMessageCount(convId, 1);
    }
  }
}
