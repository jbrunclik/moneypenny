/**
 * Active request tracking: the abort handles of in-flight sends, per request.
 *
 * The store's activeRequests map holds the UI-facing snapshot (content,
 * thinking trace) for restoring a conversation; this module owns the
 * AbortControllers the stop button and logout act on.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { clearAllInflightStreams } from './inflight-streams';

const log = createLogger('messaging');

// Track active requests per conversation to allow continuation when switching
export interface ActiveRequest {
  conversationId: string;
  type: 'stream' | 'batch';
  abortController?: AbortController;
}

const activeRequests = new Map<string, ActiveRequest>();

export function trackRequest(requestId: string, request: ActiveRequest): void {
  activeRequests.set(requestId, request);
}

export function untrackRequest(requestId: string): void {
  activeRequests.delete(requestId);
}

/**
 * Abort a streaming request for a conversation.
 * Called when user clicks the stop button.
 * Returns true if a request was found and aborted.
 */
export function abortStreamingRequest(convId: string): boolean {
  for (const [requestId, request] of activeRequests.entries()) {
    if (request.conversationId === convId && request.type === 'stream' && request.abortController) {
      log.info('Aborting streaming request', { conversationId: convId, requestId });
      request.abortController.abort();
      return true;
    }
  }
  return false;
}

/**
 * Abort every in-flight request and drop the persisted resume entries.
 * Called on logout: readers must not keep writing into a logged-out UI,
 * and a different account on this browser must not try to resume the
 * previous user's turns.
 */
export function abortAllStreamingRequests(): void {
  for (const [requestId, request] of activeRequests.entries()) {
    request.abortController?.abort();
    activeRequests.delete(requestId);
  }
  clearAllInflightStreams();
}

/**
 * Handle stop button click - abort current streaming request.
 * This is passed to MessageInput as the onStop callback.
 */
export function handleStopStreaming(): void {
  const currentConvId = useStore.getState().currentConversation?.id;
  if (currentConvId) {
    const aborted = abortStreamingRequest(currentConvId);
    if (!aborted) {
      log.warn('No streaming request found to abort', { conversationId: currentConvId });
    }
  }
}

/**
 * Point the conversation's tracked stream request at a new controller so the
 * stop button (handleStopStreaming) aborts the reader that is actually live.
 */
export function swapAbortController(convId: string, controller: AbortController): void {
  for (const request of activeRequests.values()) {
    if (request.conversationId === convId && request.type === 'stream') {
      request.abortController = controller;
    }
  }
}
