/**
 * ThinkingIndicator - Shows model thinking state and tool activity during streaming
 *
 * Displays:
 * - Full trace of thinking and tool events with details
 * - Thinking state with thinking text preview
 * - Tool execution status with query/URL/prompt details
 * - Automatically collapses into a "Show details" toggle when message is finalized
 */

import {
  SEARCH_ICON,
  LINK_ICON,
  SPARKLES_ICON,
  CHEVRON_RIGHT_ICON,
  BRAIN_ICON,
  CODE_ICON,
  CHECKLIST_ICON,
  CALENDAR_ICON,
} from '../utils/icons';
import { escapeHtml } from '../utils/dom';
import { renderMarkdown } from '../utils/markdown';
import type { ThinkingState, ThinkingTraceItem } from '../types/api';

/** Map icon keys to SVG strings - used by metadata from backend */
const ICON_MAP: Record<string, string> = {
  search: SEARCH_ICON,
  link: LINK_ICON,
  sparkles: SPARKLES_ICON,
  code: CODE_ICON,
  checklist: CHECKLIST_ICON,
  calendar: CALENDAR_ICON,
  brain: BRAIN_ICON,
};

/**
 * Get icon for a trace item (prefers metadata, falls back to brain icon)
 */
function getToolIcon(item: ThinkingTraceItem): string {
  if (item.type === 'thinking') return BRAIN_ICON;
  if (item.metadata?.icon) return ICON_MAP[item.metadata.icon] || BRAIN_ICON;
  return BRAIN_ICON;
}

/**
 * Get display label for a trace item (prefers metadata, falls back to tool name)
 */
function getToolLabel(item: ThinkingTraceItem): string {
  if (item.type === 'thinking') return 'Thinking';

  if (item.completed) {
    // Use past tense label from metadata if available
    return item.metadata?.label_past || `Used ${item.label}`;
  } else {
    // Use present tense label from metadata if available
    return item.metadata?.label || `Running ${item.label}`;
  }
}

/**
 * Truncate text to a maximum length with ellipsis
 */
function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - 1) + '…';
}

/**
 * Render a single trace item (thinking or tool)
 * @param item The trace item to render
 * @param isActive Whether this item is currently active (shows dots animation)
 * @param showFullDetail If true, don't truncate detail text (used in finalized view)
 */
function renderTraceItem(item: ThinkingTraceItem, isActive: boolean, showFullDetail = false): string {
  const icon = getToolIcon(item);
  const displayLabel = getToolLabel(item);

  const statusClass = item.completed ? 'completed' : (isActive ? 'active' : '');
  const dots = isActive && !item.completed
    ? '<span class="thinking-dots"><span></span><span></span><span></span></span>'
    : '';
  const checkmark = item.completed ? '<span class="thinking-checkmark">✓</span>' : '';

  // Show detail if available
  // For thinking items, render as markdown; for tools, truncate unless in finalized view
  // Exception: generate_image prompts are always shown in full (they're creative content)
  let detailHtml = '';
  if (item.detail) {
    if (item.type === 'thinking') {
      // Render thinking text as markdown for better readability
      detailHtml = `<div class="thinking-detail thinking-markdown">${renderMarkdown(item.detail)}</div>`;
    } else {
      // Show full detail for generate_image (prompts are creative content worth showing)
      const isImagePrompt = item.label === 'generate_image';
      const shouldTruncate = !showFullDetail && !isImagePrompt;
      const detailText = shouldTruncate ? truncateText(item.detail, 60) : item.detail;
      // Add 'full-detail' class for image prompts to override CSS truncation
      const detailClass = isImagePrompt ? 'thinking-detail full-detail' : 'thinking-detail';
      detailHtml = `<span class="${detailClass}">${escapeHtml(detailText)}</span>`;
    }
  }

  return `
    <div class="thinking-trace-item ${statusClass}">
      <span class="thinking-icon">${icon}</span>
      <span class="thinking-label">${escapeHtml(displayLabel)}</span>
      ${detailHtml}
      ${dots}
      ${checkmark}
    </div>
  `;
}

/**
 * Create a thinking indicator element for a streaming message
 * @returns HTMLElement that can be inserted at the top of the message bubble
 */
export function createThinkingIndicator(): HTMLElement {
  const container = document.createElement('div');
  container.className = 'thinking-indicator';
  container.setAttribute('aria-live', 'polite');
  container.setAttribute('aria-label', 'AI is processing');

  // Inner content will be updated dynamically
  container.innerHTML = `
    <div class="thinking-indicator-content">
      <div class="thinking-trace">
        <div class="thinking-trace-item active">
          <span class="thinking-icon">${BRAIN_ICON}</span>
          <span class="thinking-label">Thinking</span>
          <span class="thinking-dots"><span></span><span></span><span></span></span>
        </div>
      </div>
    </div>
  `;

  return container;
}

/**
 * Update the thinking indicator with current state
 */
export function updateThinkingIndicator(
  container: HTMLElement,
  state: ThinkingState
): void {
  const content = container.querySelector('.thinking-indicator-content');
  if (!content) return;

  // Build trace from state
  const traceItems: string[] = [];

  // Render all trace items
  for (let i = 0; i < state.trace.length; i++) {
    const item = state.trace[i];
    // Thinking item is active if isThinking is true and no tool is active
    // Tool item is active if it matches the currently active tool and is not completed
    let isActive = false;
    if (item.type === 'thinking') {
      isActive = state.isThinking && !state.activeTool;
    } else {
      // Tool is active if it matches the currently active tool and is not completed
      isActive = state.activeTool === item.label && !item.completed;
    }
    traceItems.push(renderTraceItem(item, isActive));
  }

  // If trace is empty but we're thinking, show the initial thinking state
  if (traceItems.length === 0 && state.isThinking) {
    traceItems.push(`
      <div class="thinking-trace-item active">
        <span class="thinking-icon">${BRAIN_ICON}</span>
        <span class="thinking-label">Thinking</span>
        <span class="thinking-dots"><span></span><span></span><span></span></span>
      </div>
    `);
  }

  content.innerHTML = `
    <div class="thinking-trace">
      ${traceItems.join('')}
    </div>
  `;
}

/**
 * Finalize the thinking indicator - collapse into a toggle
 * @param container The thinking indicator element
 * @param state Final state with thinking text and completed tools
 */
export function finalizeThinkingIndicator(
  container: HTMLElement,
  state: ThinkingState
): void {
  // If there's no meaningful content to show, remove the indicator
  if (!state.thinkingText && state.completedTools.length === 0 && state.trace.length === 0) {
    container.remove();
    return;
  }

  // Add finalized class for styling
  container.classList.add('finalized');
  container.classList.remove('streaming');

  // Reorder trace for finalized view: thinking first, then tools (logical reading order)
  // During streaming, thinking is at the end for auto-scroll, but for reading it makes sense first
  const reorderedTrace = [
    ...state.trace.filter(item => item.type === 'thinking'),
    ...state.trace.filter(item => item.type === 'tool'),
  ];

  // Render the collapsed toggle with full trace in details
  // Pass showFullDetail=true to show full text in finalized view
  const traceItems: string[] = [];

  for (const item of reorderedTrace) {
    traceItems.push(renderTraceItem({ ...item, completed: true }, false, true));
  }

  // If no trace but we have thinking text or completed tools, build from those
  if (traceItems.length === 0) {
    if (state.thinkingText) {
      traceItems.push(renderTraceItem({
        type: 'thinking',
        label: 'thinking',
        detail: state.thinkingText,
        completed: true,
      }, false, true));
    }
    for (const tool of state.completedTools) {
      traceItems.push(renderTraceItem({
        type: 'tool',
        label: tool,
        completed: true,
      }, false, true));
    }
  }

  // Create collapsible structure
  container.innerHTML = `
    <button class="thinking-toggle" aria-expanded="false" type="button">
      <span class="thinking-toggle-icon">${CHEVRON_RIGHT_ICON}</span>
      <span class="thinking-toggle-summary">Show details</span>
    </button>
    <div class="thinking-details" hidden>
      <div class="thinking-trace">
        ${traceItems.join('')}
      </div>
    </div>
  `;

  // Add toggle behavior
  const toggle = container.querySelector('.thinking-toggle');
  const details = container.querySelector('.thinking-details');

  if (toggle && details) {
    toggle.addEventListener('click', () => {
      const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!isExpanded));
      details.toggleAttribute('hidden', isExpanded);
      container.classList.toggle('expanded', !isExpanded);

      // Update summary text
      const summary = toggle.querySelector('.thinking-toggle-summary');
      if (summary) {
        summary.textContent = isExpanded ? 'Show details' : 'Hide details';
      }
    });
  }
}

/**
 * Initialize thinking indicator state
 */
export function createThinkingState(): ThinkingState {
  return {
    isThinking: true,
    thinkingText: '',
    activeTool: null,
    activeToolDetail: undefined,
    completedTools: [],
    // Start with empty trace - thinking will be added at the END when it arrives
    // This ensures thinking stays at bottom during streaming for proper auto-scroll
    trace: [],
  };
}

/**
 * Add a thinking event to the trace
 * Thinking is a singleton - there's always exactly one thinking item at the END of the trace.
 * Keeping thinking at the end ensures auto-scroll follows the active content during streaming.
 */
export function addThinkingToTrace(state: ThinkingState, text: string): void {
  // Find the ONE thinking item (should be at the END of the trace)
  const thinkingItem = state.trace.find(item => item.type === 'thinking');

  if (thinkingItem) {
    // Update the detail with the new thinking text (accumulates)
    thinkingItem.detail = text;
    // Mark as not completed since we're actively thinking
    thinkingItem.completed = false;
  } else {
    // Add thinking at the END of trace for proper auto-scroll during streaming
    state.trace.push({
      type: 'thinking',
      label: 'thinking',
      detail: text,
      completed: false,
    });
  }

  state.thinkingText = text;
  state.isThinking = true;
}

/**
 * Add a tool start event to the trace
 * Tools are inserted BEFORE thinking to keep thinking at the end for auto-scroll
 */
export function addToolStartToTrace(
  state: ThinkingState,
  tool: string,
  detail?: string,
  metadata?: import('../types/api').ToolMetadata
): void {
  // Mark thinking as completed (tool is now active)
  const thinkingIndex = state.trace.findIndex(item => item.type === 'thinking');
  if (thinkingIndex !== -1) {
    state.trace[thinkingIndex].completed = true;
  }

  // Create the new tool item with metadata for display
  const toolItem: ThinkingTraceItem = {
    type: 'tool',
    label: tool,
    detail,
    completed: false,
    metadata,
  };

  // Insert tool BEFORE thinking to keep thinking at the end for auto-scroll
  if (thinkingIndex !== -1) {
    state.trace.splice(thinkingIndex, 0, toolItem);
  } else {
    // No thinking item yet, just push
    state.trace.push(toolItem);
  }

  state.activeTool = tool;
  state.activeToolDetail = detail;
  state.isThinking = false;
}

/**
 * Update the detail for an active (non-completed) tool in the trace.
 * Used when tool_call_chunks accumulate enough args to extract the detail.
 */
export function updateToolDetailInTrace(state: ThinkingState, tool: string, detail: string): void {
  // Find the tool in trace that matches and is not completed
  for (const item of state.trace) {
    if (item.type === 'tool' && item.label === tool && !item.completed) {
      item.detail = detail;
      break;
    }
  }

  // Update active tool detail if this is the currently active tool
  if (state.activeTool === tool) {
    state.activeToolDetail = detail;
  }
}

/**
 * Mark a tool as completed in the trace
 */
export function markToolCompletedInTrace(state: ThinkingState, tool: string): void {
  // Find the tool in trace and mark it completed
  for (const item of state.trace) {
    if (item.type === 'tool' && item.label === tool && !item.completed) {
      item.completed = true;
      break;
    }
  }

  if (!state.completedTools.includes(tool)) {
    state.completedTools.push(tool);
  }

  if (state.activeTool === tool) {
    state.activeTool = null;
    state.activeToolDetail = undefined;
  }
}
