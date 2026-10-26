/**
 * Progress of a streaming reply before and between its text: thinking, tool
 * calls and the "model busy - retrying" status, shown in its thinking
 * indicator.
 */
import {
  updateThinkingIndicator,
  addThinkingToTrace,
  addToolStartToTrace,
  updateToolDetailInTrace,
  markToolCompletedInTrace,
} from '../ThinkingIndicator';
import { getStreamingContext } from './streaming-context';
import { autoScrollForStreaming } from './stream-follow';
import type { ToolMetadata } from '../../types/api';

/**
 * Update the thinking state of the current streaming message
 */
export function updateStreamingThinking(thinkingText?: string): void {
  const context = getStreamingContext();
  if (!context) return;
  clearStreamingRetryStatus();

  if (thinkingText) {
    addThinkingToTrace(context.thinkingState, thinkingText);
  }
  context.thinkingState.isThinking = true;

  updateThinkingIndicator(
    context.thinkingIndicator,
    context.thinkingState
  );

  // Auto-scroll to keep thinking indicator visible
  autoScrollForStreaming();
}

/**
 * Signal that a tool has started executing
 * @param toolName The name of the tool
 * @param detail Optional detail (search query, URL, prompt)
 * @param metadata Optional metadata from backend for display (label, icon)
 */
export function updateStreamingToolStart(
  toolName: string,
  detail?: string,
  metadata?: ToolMetadata
): void {
  const context = getStreamingContext();
  if (!context) return;
  clearStreamingRetryStatus();

  addToolStartToTrace(context.thinkingState, toolName, detail, metadata);

  updateThinkingIndicator(
    context.thinkingIndicator,
    context.thinkingState
  );

  // Auto-scroll to keep tool indicator visible
  autoScrollForStreaming();
}

/**
 * Update the detail for an active tool (e.g., when streaming args become available)
 * @param toolName The name of the tool
 * @param detail The detail to show (e.g., action, query)
 */
export function updateStreamingToolDetail(toolName: string, detail: string): void {
  const context = getStreamingContext();
  if (!context) return;

  updateToolDetailInTrace(context.thinkingState, toolName, detail);

  updateThinkingIndicator(
    context.thinkingIndicator,
    context.thinkingState
  );

  // Auto-scroll to keep tool indicator visible
  autoScrollForStreaming();
}

/**
 * Signal that a tool has finished executing
 */
export function updateStreamingToolEnd(toolName: string): void {
  const context = getStreamingContext();
  if (!context) return;

  markToolCompletedInTrace(context.thinkingState, toolName);

  updateThinkingIndicator(
    context.thinkingIndicator,
    context.thinkingState
  );

  // Auto-scroll after tool completion
  autoScrollForStreaming();
}

const RETRY_STATUS_CLASS = 'streaming-retry-status';

/**
 * Show that a transient model error (Gemini 503/429) is being retried.
 *
 * The backoff can run tens of seconds; without this the turn looked hung.
 * Lives next to (not inside) the re-rendered trace, and is cleared as soon
 * as the model makes progress (thinking, tool call, token) or the turn ends.
 */
export function updateStreamingRetryStatus(attempt: number, maxRetries?: number): void {
  const context = getStreamingContext();
  if (!context) return;
  const indicator = context.thinkingIndicator;
  let status = indicator.querySelector<HTMLElement>(`.${RETRY_STATUS_CLASS}`);
  if (!status) {
    status = document.createElement('div');
    status.className = RETRY_STATUS_CLASS;
    indicator.appendChild(status);
  }
  const progress = maxRetries ? ` (attempt ${attempt} of ${maxRetries})` : '';
  status.textContent = `The model is busy - retrying${progress}…`;
  autoScrollForStreaming();
}

/** Remove the retry status line, if shown. */
export function clearStreamingRetryStatus(): void {
  getStreamingContext()?.thinkingIndicator
    .querySelector(`.${RETRY_STATUS_CLASS}`)
    ?.remove();
}
