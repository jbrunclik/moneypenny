/**
 * ThinkingIndicator - Shows model thinking state and tool activity during streaming
 *
 * Displays:
 * - Full trace of thinking and tool events with details
 * - Thinking state with thinking text preview
 * - Tool execution status with query/URL/prompt details
 * - Collapses into a one-line summary toggle ("Thought · Searched ×3") when finalized
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
  GLOBE_ICON,
  DATABASE_ICON,
  HISTORY_ICON,
  ACTIVITY_ICON,
  MAP_PIN_ICON,
  FILE_ICON,
  ROBOT_ICON,
  LOCK_ICON,
  SOURCES_ICON,
  EDIT_ICON,
  REFRESH_ICON,
  IMAGE_ICON,
  PHONE_ICON,
} from '../utils/icons';
import { escapeHtml, isScrolledToBottom } from '../utils/dom';
import { beginProgrammaticScroll, endProgrammaticScroll } from '../utils/thumbnails';
import { renderMarkdown } from '../utils/markdown';
import type { ThinkingState, ThinkingTraceItem } from '../types/api';

/** Map icon keys to SVG strings - used by metadata from backend */
const ICON_MAP: Record<string, string> = {
  search: SEARCH_ICON,
  link: LINK_ICON,
  globe: GLOBE_ICON,
  sparkles: SPARKLES_ICON,
  code: CODE_ICON,
  checklist: CHECKLIST_ICON,
  calendar: CALENDAR_ICON,
  brain: BRAIN_ICON,
  database: DATABASE_ICON,
  history: HISTORY_ICON,
  activity: ACTIVITY_ICON,
  'map-pin': MAP_PIN_ICON,
  file: FILE_ICON,
  robot: ROBOT_ICON,
  lock: LOCK_ICON,
  sources: SOURCES_ICON,
  edit: EDIT_ICON,
  refresh: REFRESH_ICON,
  image: IMAGE_ICON,
  message: PHONE_ICON,
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

/** Steps named in a finalized summary before the rest fold into "+N more" */
const SUMMARY_MAX_PARTS = 3;

/**
 * One-line summary of a finished turn's trace ("Thought · Searched ×3 ·
 * Fetched") - says what happened instead of a generic "Show details".
 * Steps with the same label merge in first-seen order, counted when repeated.
 */
function summarizeTrace(items: ThinkingTraceItem[]): string {
  const counts = new Map<string, number>();
  for (const item of items) {
    const label = item.type === 'thinking' ? 'Thought' : getToolLabel({ ...item, completed: true });
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const parts = [...counts].map(([label, n]) => (n > 1 && label !== 'Thought' ? `${label} ×${n}` : label));
  if (parts.length === 0) return 'Show details';
  if (parts.length > SUMMARY_MAX_PARTS) {
    const rest = parts.length - SUMMARY_MAX_PARTS;
    return [...parts.slice(0, SUMMARY_MAX_PARTS), `+${rest} more`].join(' · ');
  }
  return parts.join(' · ');
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
function renderTraceItem(
  item: ThinkingTraceItem,
  isActive: boolean,
  showFullDetail = false,
  isCurrent = false
): string {
  const icon = getToolIcon(item);
  const displayLabel = getToolLabel(item);

  const statusClass = (item.completed ? 'completed' : (isActive ? 'active' : '')) + (isCurrent ? ' current' : '');
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
      // Render thinking text as markdown for better readability; the live
      // one-line view shows only its latest heading
      const heading = latestThoughtHeading(item.detail);
      const headingHtml = heading ? `<span class="thinking-heading">${escapeHtml(heading)}</span>` : '';
      detailHtml = `${headingHtml}<div class="thinking-detail thinking-markdown">${renderMarkdown(item.detail)}</div>`;
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

  renderLiveSkeleton(container);
  // One listener for the container's life: the live line re-renders on
  // every event, and a collapse/reopen swaps its markup
  container.addEventListener('click', (event) => {
    if (!(event.target instanceof Element) || container.classList.contains('finalized')) return;
    const expanded = container.classList.contains(LIVE_EXPANDED_CLASS);
    // The chevron toggles; a tap anywhere on the collapsed line opens it
    // (open, the text stays selectable)
    if (event.target.closest('.thinking-live-expand') || (!expanded && event.target.closest('.thinking-indicator-content'))) {
      setLiveExpanded(container, !expanded);
    }
  });
  return container;
}

const LIVE_EXPANDED_CLASS = 'live-expanded';

/** The live (streaming) markup: the expand control and the trace. */
function renderLiveSkeleton(container: HTMLElement): void {
  container.classList.remove('finalized');
  const expanded = container.classList.contains(LIVE_EXPANDED_CLASS);
  container.innerHTML = `
    <button class="thinking-live-expand" type="button" aria-expanded="${expanded}" aria-label="Show the full trace">
      ${CHEVRON_RIGHT_ICON}
    </button>
    <div class="thinking-indicator-content">
      <div class="thinking-trace">
        <div class="thinking-trace-item active current">
          <span class="thinking-icon">${BRAIN_ICON}</span>
          <span class="thinking-label">Thinking</span>
          <span class="thinking-dots"><span></span><span></span><span></span></span>
        </div>
      </div>
    </div>
  `;
}

function setLiveExpanded(container: HTMLElement, expanded: boolean): void {
  container.classList.toggle(LIVE_EXPANDED_CLASS, expanded);
  container.querySelector('.thinking-live-expand')?.setAttribute('aria-expanded', String(expanded));
}

const HEADING_MAX_CHARS = 80;

/**
 * The latest heading of a thought summary ("**Checking the docs**" lines,
 * or `#` headings) for the one-line live view; without one, the last line
 * as plain text, shortened.
 */
export function latestThoughtHeading(text: string | undefined): string {
  const lines = (text ?? '').split('\n').map((line) => line.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    const heading = /^(?:\*\*|__)(.+?)(?:\*\*|__):?$/.exec(lines[i]) ?? /^#{1,6}\s+(.+)$/.exec(lines[i]);
    if (heading) return heading[1].trim();
  }
  const last = (lines.at(-1) ?? '').replace(/[*_`#>]/g, '').trim();
  return last.length > HEADING_MAX_CHARS ? `${last.slice(0, HEADING_MAX_CHARS).trimEnd()}…` : last;
}

/**
 * The step the one-line view shows: the running one, else the last tool
 * (just finished), else the last item.
 */
function currentTraceIndex(state: ThinkingState): number {
  const active = state.trace.findIndex((item) =>
    item.type === 'thinking' ? state.isThinking && !state.activeTool : state.activeTool === item.label && !item.completed
  );
  if (active !== -1) return active;
  const lastTool = state.trace.map((item) => item.type).lastIndexOf('tool');
  return lastTool !== -1 ? lastTool : state.trace.length - 1;
}

/**
 * Update the thinking indicator with current state
 */
export function updateThinkingIndicator(
  container: HTMLElement,
  state: ThinkingState
): void {
  // A later round after the answer started (collapsed or hidden): live again
  container.hidden = false;
  if (!container.querySelector('.thinking-indicator-content')) renderLiveSkeleton(container);
  const content = container.querySelector('.thinking-indicator-content');
  if (!content) return;

  // Build trace from state
  const traceItems: string[] = [];
  const current = currentTraceIndex(state);

  // Render all trace items
  for (let i = 0; i < state.trace.length; i++) {
    const item = state.trace[i];
    // Thinking item is active if isThinking is true and no tool is active
    // Tool item is active if it matches the currently active tool and is not completed
    const isActive =
      item.type === 'thinking'
        ? state.isThinking && !state.activeTool
        : state.activeTool === item.label && !item.completed;
    traceItems.push(renderTraceItem(item, isActive, false, i === current));
  }

  // If trace is empty but we're thinking, show the initial thinking state
  if (traceItems.length === 0 && state.isThinking) {
    traceItems.push(`
      <div class="thinking-trace-item active current">
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
 * The answer started: collapse the live line into the finished summary
 * (the answer then starts right under the user's message). A later round's
 * thinking or tool reopens it (updateThinkingIndicator). An empty trace is
 * hidden, not removed - the indicator must stay for those later rounds.
 */
export function collapseThinkingIndicator(container: HTMLElement, state: ThinkingState): void {
  if (!container.querySelector('.thinking-indicator-content')) return;
  if (!state.thinkingText && state.completedTools.length === 0 && state.trace.length === 0) {
    container.hidden = true;
    return;
  }
  finalizeThinkingIndicator(container, state);
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

  // Already collapsed when the answer started, and no round since
  if (container.classList.contains('finalized')) return;

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
  // The summary names the same steps the details list
  const summaryItems: ThinkingTraceItem[] = [...reorderedTrace];

  // If no trace but we have thinking text or completed tools, build from those
  if (traceItems.length === 0) {
    if (state.thinkingText) {
      const thinking: ThinkingTraceItem = { type: 'thinking', label: 'thinking', detail: state.thinkingText, completed: true };
      traceItems.push(renderTraceItem(thinking, false, true));
      summaryItems.push(thinking);
    }
    for (const tool of state.completedTools) {
      const item: ThinkingTraceItem = { type: 'tool', label: tool, completed: true };
      traceItems.push(renderTraceItem(item, false, true));
      summaryItems.push(item);
    }
  }

  // Collapsing the expanded trace shrinks content ABOVE anything the user is
  // reading further down - without compensation their reading position jumps
  // up by the collapsed height. Measure before/after and put it back.
  const scrollContainer = document.getElementById('messages');
  const heightBefore = container.offsetHeight;

  // Opened by the user while live: stays open
  const expanded = container.classList.contains(LIVE_EXPANDED_CLASS);
  container.classList.toggle('expanded', expanded);

  // Create collapsible structure
  container.innerHTML = `
    <button class="thinking-toggle" aria-expanded="${expanded}" type="button">
      <span class="thinking-toggle-icon">${CHEVRON_RIGHT_ICON}</span>
      <span class="thinking-toggle-summary">${escapeHtml(summarizeTrace(summaryItems))}</span>
    </button>
    <div class="thinking-details"${expanded ? '' : ' hidden'}>
      <div class="thinking-trace">
        ${traceItems.join('')}
      </div>
    </div>
  `;

  if (scrollContainer) {
    const collapseDelta = heightBefore - container.offsetHeight;
    const indicatorBottom = container.getBoundingClientRect().bottom;
    const viewportTop = scrollContainer.getBoundingClientRect().top;
    // Compensate only when the collapsed area sits fully above the viewport
    // (the user is reading below it) and they aren't at the bottom anyway
    // (follow mode / bottom clamping handles that case)
    if (
      collapseDelta > 0 &&
      indicatorBottom < viewportTop &&
      // Really at the bottom (1px), not the 200px follow zone: an anchored
      // reader near the end of a long reply saw the text jump up
      !isScrolledToBottom(scrollContainer, 1)
    ) {
      endProgrammaticScroll(beginProgrammaticScroll());
      scrollContainer.scrollTop -= collapseDelta;
    }
  }

  // Add toggle behavior
  const toggle = container.querySelector('.thinking-toggle');
  const details = container.querySelector('.thinking-details');

  if (toggle && details) {
    toggle.addEventListener('click', () => {
      const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!isExpanded));
      details.toggleAttribute('hidden', isExpanded);
      container.classList.toggle('expanded', !isExpanded);
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
