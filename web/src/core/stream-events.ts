/**
 * Per-event handling for a live (or resumed) stream: updates the stream's
 * state, the store snapshot and - for the visible conversation - the DOM.
 * The terminal `done` event is handled in stream-done.ts.
 */

import { getSyncManager } from '../sync/SyncManager';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { ApiError } from '../api/http';
import {
  updateStreamingMessage,
  updateStreamingThinking,
  updateStreamingToolStart,
  updateStreamingToolDetail,
  updateStreamingToolEnd,
  updateStreamingRetryStatus,
  getStreamingMessageElement,
  updateUserMessageId,
} from '../components/messages';
import type { ToolMetadata } from '../types/api';
import { persistInflightStream } from './inflight-streams';
import { acknowledgeServerStop, type StreamingState } from './stream-session';
import { deepCopyThinkingState, updateLocalThinkingState } from './thinking-state';
import { showGroundingChecking } from '../components/messages/grounding';
import { notifyModelFallback } from './model-fallback';
import { handleResearchEvent } from './research-stream';
import { addLiveArtifact } from '../components/messages/artifacts';

const log = createLogger('messaging');

type StreamEventPayload = { type: string; [key: string]: unknown };

/** Mirror the stream's progress into the store (restored on conversation switch). */
function isArtifactRef(
  event: Record<string, unknown>
): event is { id: string; version: number; title: string } {
  return (
    typeof event.id === 'string' &&
    typeof event.version === 'number' &&
    typeof event.title === 'string'
  );
}

function snapshotToStore(state: StreamingState, convId: string): void {
  useStore.getState().updateActiveRequestContent(
    convId,
    state.fullContent,
    deepCopyThinkingState(state.thinkingState)
  );
}

function handleUserMessageSaved(
  event: StreamEventPayload,
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): void {
  if (event.user_message_id) {
    updateUserMessageId(tempUserMessageId, event.user_message_id as string);
  }
  // Capture the expected assistant message ID for stream recovery
  if (!event.expected_assistant_message_id) return;
  state.expectedAssistantMessageId = event.expected_assistant_message_id as string;
  // Persist so a crashed/reloaded page can resume this turn from the journal
  // (not another device's turn this tab merely follows - its reload would
  // resume it as its own)
  if (!state.remoteFollow) persistInflightStream(convId, state.expectedAssistantMessageId);
  log.debug('Captured expected assistant message ID', {
    conversationId: convId,
    expectedMessageId: state.expectedAssistantMessageId,
  });
  // Set the ID on the streaming element early for reliable recovery lookup
  if (state.messageEl) {
    state.messageEl.dataset.messageId = state.expectedAssistantMessageId;
  }
}

/** thinking / tool_start / tool_detail / tool_end: local trace + DOM + store. */
function handleTraceEvent(
  event: StreamEventPayload,
  state: StreamingState,
  convId: string,
  isCurrentConversation: boolean
): void {
  const tool = event.tool as string;
  const detail = event.detail as string | undefined;
  const metadata = event.metadata as ToolMetadata | undefined;
  switch (event.type) {
    case 'thinking':
      updateLocalThinkingState(state.thinkingState, 'thinking', event.text as string);
      if (isCurrentConversation) {
        updateStreamingThinking(event.text as string);
      }
      break;
    case 'tool_start':
      updateLocalThinkingState(state.thinkingState, 'tool_start', tool, detail, metadata);
      if (isCurrentConversation) {
        updateStreamingToolStart(tool, detail, metadata);
      }
      break;
    case 'tool_detail':
      updateLocalThinkingState(state.thinkingState, 'tool_detail', tool, detail);
      if (isCurrentConversation && detail) {
        updateStreamingToolDetail(tool, detail);
      }
      break;
    case 'tool_end':
      updateLocalThinkingState(state.thinkingState, 'tool_end', tool);
      if (isCurrentConversation) {
        updateStreamingToolEnd(tool);
      }
      break;
  }
  snapshotToStore(state, convId);
}

function handleToken(
  event: StreamEventPayload,
  state: StreamingState,
  convId: string,
  isCurrentConversation: boolean
): void {
  state.fullContent += event.text as string;
  state.tokenCount = (state.tokenCount ?? 0) + 1;
  if (state.thinkingState.isThinking) {
    state.thinkingState.isThinking = false;
  }
  snapshotToStore(state, convId);
  if (isCurrentConversation) {
    updateStreamingMessage(state.messageEl, state.fullContent);
  } else if (state.tokenCount === 1) {
    // Log when tokens are not rendered (helps diagnose streaming issues)
    log.warn('Token received but not current conversation', {
      conversationId: convId,
      currentConversation: useStore.getState().currentConversation?.id,
    });
  }
  // Log first token and periodically to track streaming progress
  if (state.tokenCount === 1 || state.tokenCount % 50 === 0) {
    log.debug('Token streaming progress', {
      tokenCount: state.tokenCount,
      contentLength: state.fullContent.length,
      isCurrentConversation,
    });
  }
}

/** Thinking-trace events (persisted with the reply) */
const TRACE_EVENT_TYPES: ReadonlySet<string> = new Set(['thinking', 'tool_start', 'tool_detail', 'tool_end']);

/** Deep-research progress events */
const RESEARCH_EVENT_TYPES: ReadonlySet<string> = new Set([
  'research_plan',
  'research_item',
  'research_finding',
  'research_sources',
  'research_writing',
]);

/**
 * Status notices about the turn (fallback model, grounding check, server
 * stop, retries, approval). Returns false when the event is not one.
 */
function handleNoticeEvent(
  event: StreamEventPayload,
  state: StreamingState,
  convId: string,
  isCurrentConversation: boolean
): boolean {
  switch (event.type) {
    case 'model_fallback':
      if (isCurrentConversation && typeof event.to === 'string') notifyModelFallback(event.to);
      return true;

    case 'grounding_started':
      // The verifier runs between the last token and done (~1 s)
      if (isCurrentConversation) showGroundingChecking(state.messageEl);
      return true;

    case 'stopping':
      // Server-side Stop acknowledged: the done event follows at the next checkpoint
      acknowledgeServerStop(state);
      return true;

    case 'retry':
      // Transient Gemini error being retried server-side: show it instead
      // of a silent stall (not part of the persisted thinking trace)
      if (isCurrentConversation) {
        updateStreamingRetryStatus(event.attempt as number, event.max_retries as number | undefined);
      }
      return true;

    case 'approval_required':
      // Agent requested approval - update UI state
      // The done event will follow with the full message
      log.info('Approval requested', {
        approvalId: event.approval_id,
        description: event.description,
        conversationId: convId,
      });
      return true;

    default:
      return false;
  }
}

/** A version of an artifact is ready: its frame loads while the reply keeps streaming. */
function handleArtifactEvent(
  event: StreamEventPayload,
  state: StreamingState,
  convId: string,
  isCurrentConversation: boolean
): void {
  if (!isArtifactRef(event)) return;
  const ref = { id: event.id, version: event.version, title: event.title };
  // Kept with the turn, so switching away and back restores the card
  useStore.getState().addActiveRequestArtifact(convId, ref);
  if (isCurrentConversation && state.messageEl) addLiveArtifact(state.messageEl, ref);
}

/**
 * Process a single streaming event and update state/UI.
 */
export function processStreamEvent(
  event: StreamEventPayload,
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): { shouldBreak?: boolean; error?: Error } {
  const isCurrentConversation = useStore.getState().currentConversation?.id === convId;

  // Update message element reference (may have been restored after conversation switch)
  const currentMessageEl = getStreamingMessageElement(convId);
  if (currentMessageEl) {
    state.messageEl = currentMessageEl;
  }

  if (TRACE_EVENT_TYPES.has(event.type)) {
    handleTraceEvent(event, state, convId, isCurrentConversation);
  } else if (RESEARCH_EVENT_TYPES.has(event.type)) {
    handleResearchEvent(event, state, convId, isCurrentConversation);
  } else if (!handleNoticeEvent(event, state, convId, isCurrentConversation)) {
    switch (event.type) {
      case 'user_message_saved':
        handleUserMessageSaved(event, state, convId, tempUserMessageId);
        // (a followed stream's replayed event is the other device's message)
        if (!state.remoteFollow) getSyncManager()?.noteOwnMessageSaved(convId);
        break;

      case 'artifact':
        handleArtifactEvent(event, state, convId, isCurrentConversation);
        break;

      case 'token':
        handleToken(event, state, convId, isCurrentConversation);
        break;

      case 'error':
        return handleStreamError(event, state);
    }
  }

  return {};
}

/**
 * Handle stream error event.
 */
function handleStreamError(
  event: { type: string; message?: string; code?: string; retryable?: boolean },
  state: StreamingState
): { error: Error } {
  log.error('Stream error', { message: event.message });
  state.serverError = true;

  if (state.fullContent.trim()) {
    state.messageEl.classList.add('message-incomplete');
  } else {
    state.messageEl.remove();
  }

  const streamError = new ApiError(
    event.message || 'Failed to generate response.',
    event.code === 'TIMEOUT' ? 408 : 500,
    {
      ...(event.code !== undefined && { code: event.code }),
      retryable: event.retryable ?? false,
      isTimeout: event.code === 'TIMEOUT',
    }
  );

  return { error: streamError };
}
