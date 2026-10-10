/**
 * Streaming session lifecycle: per-stream mutable state, request
 * registration/cleanup, and the background/foreground listeners shared by
 * the live stream and the reload-resume path.
 */

import { settleTurnFor } from '../components/messages/turn-anchor';
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
import { conversations } from '../api/conversations';
import { STOP_DONE_GRACE_MS } from '../config';
import { hasTrackedRequestFor, trackRequest, untrackRequest } from './active-requests';
import { markStreamForRecovery } from './stream-recovery';
import { createThinkingState } from './thinking-state';
import type { ResearchProgress } from '../components/messages/research-progress';

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
  /** Stop was sent to the server; a done event with stop_reason 'user' is expected */
  stopRequested?: boolean;
  /** Grace timer that aborts the reader if that done event never arrives */
  stopTimer?: ReturnType<typeof setTimeout>;
  /** Count of token events received (for debugging) */
  tokenCount?: number;
  /** A deep-research turn's progress (research_* events) */
  research?: ResearchProgress;
  /** The server's message count once the turn finished (done event) */
  serverMessageCount?: number;
  /** Following another device's turn (followRemoteStream), not our own */
  remoteFollow?: boolean;
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
 * Stop pressed: once the server has the turn (user_message_saved gave us the
 * assistant id), ask it to stop and keep reading - the done event brings the
 * saved partial reply. Before that, return false so Stop aborts the reader.
 * Shared by the live stream and the reload-resume reader.
 */
export function requestServerStop(convId: string, state: StreamingState): boolean {
  if (state.stopRequested) return true;
  if (!state.expectedAssistantMessageId) return false;
  state.stopRequested = true;
  conversations.stop(convId, state.expectedAssistantMessageId).catch((error: unknown) => {
    log.warn('Server stop request failed - aborting reader', { conversationId: convId, error });
    state.activeAbortController?.abort();
  });
  state.stopTimer = setTimeout(() => state.activeAbortController?.abort(), STOP_DONE_GRACE_MS);
  return true;
}

/**
 * The server acknowledged the Stop ("stopping" event): the done event follows
 * at the turn's next checkpoint - possibly after a long tool - so the grace
 * abort must not cut it off.
 */
export function acknowledgeServerStop(state: StreamingState): void {
  if (state.stopTimer) {
    clearTimeout(state.stopTimer);
    state.stopTimer = undefined;
  }
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
  messageSuccessful: boolean,
  serverMessageCount?: number
): void {
  untrackRequest(requestId);
  // The sync baseline BEFORE the streaming flag clears below: clearing it
  // applies any summary deferred during the turn against this count
  if (serverMessageCount !== undefined) {
    getSyncManager()?.setLocalMessageCount(convId, serverMessageCount);
  } else if (messageSuccessful) {
    getSyncManager()?.incrementLocalMessageCount(convId, 2);
  }
  if (messageSuccessful) notifyTurnFinished();
  // A newer turn already started in this conversation (a follow-up sent while
  // this one fetched its cost, an autostarted deep research): the shared
  // per-conversation state is the new turn's now - leave it alone
  if (hasTrackedRequestFor(convId)) return;

  // However the turn ended, its reserved send-to-top space goes back
  settleTurnFor(convId);
  cleanupStreamingContext();
  useStore.getState().removeActiveRequest(convId);

  hideUploadProgress();
  useStore.getState().setUploadProgress(null);

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
