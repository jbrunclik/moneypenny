/**
 * Per-event handling for a live (or resumed) stream: updates the stream's
 * state, the store snapshot and - for the visible conversation - the DOM.
 * The terminal `done` event is handled in stream-done.ts.
 */

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
import type { StreamingState } from './stream-session';
import { deepCopyThinkingState, updateLocalThinkingState } from './thinking-state';

const log = createLogger('messaging');

type StreamEventPayload = { type: string; [key: string]: unknown };

/** Mirror the stream's progress into the store (restored on conversation switch). */
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
  persistInflightStream(convId, state.expectedAssistantMessageId);
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

  switch (event.type) {
    case 'user_message_saved':
      handleUserMessageSaved(event, state, convId, tempUserMessageId);
      break;

    case 'thinking':
    case 'tool_start':
    case 'tool_detail':
    case 'tool_end':
      handleTraceEvent(event, state, convId, isCurrentConversation);
      break;

    case 'retry':
      // Transient Gemini error being retried server-side: show it instead
      // of a silent stall (not part of the persisted thinking trace)
      if (isCurrentConversation) {
        updateStreamingRetryStatus(event.attempt as number, event.max_retries as number | undefined);
      }
      break;

    case 'token':
      handleToken(event, state, convId, isCurrentConversation);
      break;

    case 'approval_required':
      // Agent requested approval - update UI state
      // The done event will follow with the full message
      log.info('Approval requested', {
        approvalId: event.approval_id,
        description: event.description,
        conversationId: convId,
      });
      break;

    case 'error':
      return handleStreamError(event, state);
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

  if (state.fullContent.trim()) {
    state.messageEl.classList.add('message-incomplete');
  } else {
    state.messageEl.remove();
  }

  const streamError = new ApiError(
    event.message || 'Failed to generate response.',
    event.code === 'TIMEOUT' ? 408 : 500,
    {
      code: event.code,
      retryable: event.retryable ?? false,
      isTimeout: event.code === 'TIMEOUT',
    }
  );

  return { error: streamError };
}
