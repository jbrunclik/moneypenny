/**
 * Streaming session lifecycle: per-stream mutable state, request
 * registration/cleanup, and the background/foreground listeners shared by
 * the live stream and the reload-resume path.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import {
  addStreamingMessage,
  cleanupStreamingContext,
} from '../components/messages';
import { hideUploadProgress, showUploadProgress } from '../components/MessageInput';
import type { ThinkingState } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';
import { notifyTurnFinished } from './attention';
import { trackRequest, untrackRequest } from './active-requests';
import { markStreamForRecovery } from './stream-recovery';
import { createThinkingState } from './thinking-state';

const log = createLogger('messaging');

/**
 * State for a streaming request, encapsulating all mutable data.
 */
export interface StreamingState {
  messageEl: HTMLElement;
  fullContent: string;
  thinkingState: ThinkingState;
  messageSuccessful: boolean;
  uploadProgressHidden: boolean;
  /** Pre-generated assistant message ID from server, used for stream recovery */
  expectedAssistantMessageId: string | null;
  /** Highest journal seq rendered so far (resume offset for resumable streams) */
  lastSeq: number;
  /** Set before aborting the reader to resume proactively (foreground/pageshow) */
  resumeViaAbort?: boolean;
  /** The controller wired to the CURRENT reader (initial stream or a resume
   * attempt) - the stop button and the proactive bg/fg abort target this */
  activeAbortController?: AbortController;
  /** Count of token events received (for debugging) */
  tokenCount?: number;
}

export function createStreamingState(
  messageEl: HTMLElement,
  overrides: Partial<StreamingState> = {}
): StreamingState {
  return {
    messageEl,
    fullContent: '',
    thinkingState: createThinkingState(),
    messageSuccessful: false,
    uploadProgressHidden: false,
    expectedAssistantMessageId: null,
    lastSeq: 0,
    ...overrides,
  };
}

/**
 * Track a stream request (abort handle) and register it in the store for UI
 * restoration on conversation switch.
 */
export function registerStreamRequest(
  convId: string,
  requestId: string,
  abortController: AbortController
): void {
  trackRequest(requestId, {
    conversationId: convId,
    type: 'stream',
    abortController,
  });

  // Register in store for UI restoration
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'stream',
    content: '',
    thinkingState: undefined,
  });

  // Mark streaming state
  getSyncManager()?.setConversationStreaming(convId, true);
  useStore.getState().setStreamingConversation(convId);
}

/**
 * Initialize streaming request state and tracking.
 */
export function initStreamingRequest(
  convId: string,
  hasFiles: boolean
): { state: StreamingState; requestId: string; abortController: AbortController } {
  const messageEl = addStreamingMessage(convId);
  // While the multipart body (attachments) uploads, nothing is thinking
  // server-side yet - keep the assistant bubble hidden until the first
  // stream event acks that the server has the message
  if (hasFiles) {
    messageEl.classList.add('awaiting-upload');
  }
  const requestId = `stream-${convId}-${Date.now()}`;
  const abortController = new AbortController();
  registerStreamRequest(convId, requestId, abortController);

  // Show upload progress if needed. The streaming path uploads via fetch,
  // which has no progress events - show the indeterminate spin.
  if (hasFiles) {
    showUploadProgress(true);
  }

  const state = createStreamingState(messageEl, { activeAbortController: abortController });
  return { state, requestId, abortController };
}

/**
 * Clean up streaming request resources.
 */
export function cleanupStreamingRequest(
  requestId: string,
  convId: string,
  messageSuccessful: boolean
): void {
  untrackRequest(requestId);
  cleanupStreamingContext();
  useStore.getState().removeActiveRequest(convId);

  hideUploadProgress();
  useStore.getState().setUploadProgress(null);

  if (messageSuccessful) {
    getSyncManager()?.incrementLocalMessageCount(convId, 2);
    notifyTurnFinished();
  }

  getSyncManager()?.setConversationStreaming(convId, false);
  // Only clear the global flag if it is OURS - another conversation may have
  // started streaming meanwhile (concurrent conversations)
  if (useStore.getState().streamingConversationId === convId) {
    useStore.getState().setStreamingConversation(null);
  }
}

/**
 * Background/foreground handling shared by the live stream and the
 * reload-resume path. On hidden: mark for poll recovery (legacy fallback).
 * On visible after a real background stint (or a bfcache restore): the reader
 * is often silently dead (iOS froze the page / dropped the socket) and would
 * otherwise hang until the read timeout - abort it and resume from the
 * journal offset instead. Aborting BEFORE resuming also removes the
 * recovery-vs-late-reader race (R13: buffered bytes overwriting recovery).
 * Returns a cleanup function that removes the listeners.
 */
export function setupStreamLifecycleListeners(state: StreamingState, convId: string): () => void {
  let hiddenAt: number | null = null;

  const proactiveResume = (): void => {
    if (state.messageSuccessful || !state.expectedAssistantMessageId) return;
    log.info('Foregrounded mid-stream - aborting reader and resuming from journal', {
      conversationId: convId,
      lastSeq: state.lastSeq,
    });
    state.resumeViaAbort = true;
    state.activeAbortController?.abort();
  };

  const handleVisibilityChange = (): void => {
    if (document.visibilityState === 'hidden') {
      hiddenAt = Date.now();
      if (state.expectedAssistantMessageId) {
        markStreamForRecovery(convId, state.expectedAssistantMessageId, state.fullContent, 'visibility');
      }
    } else if (document.visibilityState === 'visible') {
      const hiddenLongEnough = hiddenAt !== null && Date.now() - hiddenAt >= 500;
      hiddenAt = null;
      if (hiddenLongEnough) {
        proactiveResume();
      }
    }
  };

  // iOS bfcache restore can skip visibilitychange entirely (R14)
  const handlePageShow = (event: PageTransitionEvent): void => {
    if (event.persisted) {
      proactiveResume();
    }
  };

  document.addEventListener('visibilitychange', handleVisibilityChange);
  window.addEventListener('pageshow', handlePageShow);
  return () => {
    document.removeEventListener('visibilitychange', handleVisibilityChange);
    window.removeEventListener('pageshow', handlePageShow);
  };
}
