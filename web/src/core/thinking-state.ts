/**
 * Per-stream thinking/tool trace state.
 *
 * Mirrors the logic in ThinkingIndicator.ts but operates on a local state
 * object so a stream's trace keeps accumulating even while the user is
 * looking at another conversation (the store snapshot restores the indicator
 * on switch-back).
 */

import type { ThinkingState, ThinkingTraceItem, ToolMetadata } from '../types/api';

export type ThinkingEventType = 'thinking' | 'tool_start' | 'tool_detail' | 'tool_end';

/** Fresh state for a stream that has not produced any events yet. */
export function createThinkingState(): ThinkingState {
  return {
    isThinking: true,
    thinkingText: '',
    activeTool: null,
    activeToolDetail: undefined,
    completedTools: [],
    trace: [],
  };
}

/**
 * Deep copy a ThinkingState to avoid reference issues when storing in Zustand.
 */
export function deepCopyThinkingState(state: ThinkingState): ThinkingState {
  return {
    isThinking: state.isThinking,
    thinkingText: state.thinkingText,
    activeTool: state.activeTool,
    activeToolDetail: state.activeToolDetail,
    completedTools: [...state.completedTools],
    trace: state.trace.map(item => ({
      type: item.type,
      label: item.label,
      detail: item.detail,
      completed: item.completed,
    })),
  };
}

function applyThinking(state: ThinkingState, text?: string): void {
  // Find existing thinking item or create one
  const thinkingItem = state.trace.find(item => item.type === 'thinking');
  if (thinkingItem) {
    thinkingItem.detail = text;
    thinkingItem.completed = false;
  } else {
    state.trace.push({
      type: 'thinking',
      label: 'thinking',
      detail: text,
      completed: false,
    });
  }
  state.thinkingText = text || '';
  state.isThinking = true;
}

function applyToolDetail(state: ThinkingState, tool?: string, detail?: string): void {
  // Update detail for an existing tool
  const toolItem = state.trace.find(
    item => item.type === 'tool' && item.label === tool && !item.completed
  );
  if (toolItem) {
    toolItem.detail = detail;
  }
  if (state.activeTool === tool) {
    state.activeToolDetail = detail;
  }
}

function applyToolStart(
  state: ThinkingState,
  tool?: string,
  detail?: string,
  metadata?: ToolMetadata
): void {
  // Mark thinking as completed
  const thinkingIndex = state.trace.findIndex(item => item.type === 'thinking');
  if (thinkingIndex !== -1) {
    state.trace[thinkingIndex].completed = true;
  }
  // Create tool item and insert before thinking (to keep thinking at end)
  const toolItem: ThinkingTraceItem = {
    type: 'tool',
    label: tool || '',
    detail,
    completed: false,
    metadata, // Include metadata from backend for display
  };
  if (thinkingIndex !== -1) {
    state.trace.splice(thinkingIndex, 0, toolItem);
  } else {
    state.trace.push(toolItem);
  }
  state.activeTool = tool || null;
  state.activeToolDetail = detail;
  state.isThinking = false;
}

function applyToolEnd(state: ThinkingState, tool?: string): void {
  // Find the tool and mark it completed
  for (const item of state.trace) {
    if (item.type === 'tool' && item.label === tool && !item.completed) {
      item.completed = true;
      break;
    }
  }
  if (tool && !state.completedTools.includes(tool)) {
    state.completedTools.push(tool);
  }
  if (state.activeTool === tool) {
    state.activeTool = null;
    state.activeToolDetail = undefined;
  }
}

/**
 * Update local thinking state based on streaming event type.
 */
export function updateLocalThinkingState(
  state: ThinkingState,
  eventType: ThinkingEventType,
  toolOrText?: string,
  detail?: string,
  metadata?: ToolMetadata
): void {
  switch (eventType) {
    case 'thinking':
      applyThinking(state, toolOrText);
      break;
    case 'tool_detail':
      applyToolDetail(state, toolOrText, detail);
      break;
    case 'tool_start':
      applyToolStart(state, toolOrText, detail, metadata);
      break;
    case 'tool_end':
      applyToolEnd(state, toolOrText);
      break;
  }
}
