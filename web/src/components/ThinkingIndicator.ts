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
  createIconElement,
  setIcon,
  type IconHtml,
} from '../utils/icons';
import { createElement, isScrolledToBottom, setSanitizedHtml } from '../utils/dom';
import { beginProgrammaticScroll, endProgrammaticScroll } from '../utils/programmatic-scroll';
import { renderMarkdown } from '../utils/markdown';
import type { ThinkingState, ThinkingTraceItem } from '../types/api';

/** Map icon keys to SVG strings - used by metadata from backend */
const ICON_MAP: Record<string, IconHtml> = {
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
function getToolIcon(item: ThinkingTraceItem): IconHtml {
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

/** Three bouncing dots: the step is running. */
function thinkingDots(): HTMLElement {
  return createElement('span', { class: 'thinking-dots' }, [
    createElement('span'),
    createElement('span'),
    createElement('span'),
  ]);
}

/**
 * A trace item's detail: thinking text as markdown (the live one-line view
 * shows only its latest heading); a tool's argument, truncated unless in the
 * finalized view - generate_image prompts always show in full (they're
 * creative content).
 */
function traceDetail(item: ThinkingTraceItem, showFullDetail: boolean): HTMLElement[] {
  if (!item.detail) return [];
  if (item.type === 'thinking') {
    const heading = latestThoughtHeading(item.detail);
    const markdown = createElement('div', { class: 'thinking-detail thinking-markdown' });
    setSanitizedHtml(markdown, renderMarkdown(item.detail));
    return heading ? [createElement('span', { class: 'thinking-heading' }, [heading]), markdown] : [markdown];
  }
  const isImagePrompt = item.label === 'generate_image';
  const shouldTruncate = !showFullDetail && !isImagePrompt;
  const detailText = shouldTruncate ? truncateText(item.detail, 60) : item.detail;
  // 'full-detail' overrides the CSS truncation for image prompts
  const detailClass = isImagePrompt ? 'thinking-detail full-detail' : 'thinking-detail';
  return [createElement('span', { class: detailClass }, [detailText])];
}

/**
 * A single trace item (thinking or tool)
 * @param item The trace item to render
 * @param isActive Whether this item is currently active (shows dots animation)
 * @param showFullDetail If true, don't truncate detail text (used in finalized view)
 */
function traceItem(
  item: ThinkingTraceItem,
  isActive: boolean,
  showFullDetail = false,
  isCurrent = false
): HTMLElement {
  const statusClass = (item.completed ? 'completed' : (isActive ? 'active' : '')) + (isCurrent ? ' current' : '');
  return createElement('div', { class: `thinking-trace-item ${statusClass}` }, [
    createIconElement('thinking-icon', getToolIcon(item)),
    createElement('span', { class: 'thinking-label' }, [getToolLabel(item)]),
    ...traceDetail(item, showFullDetail),
    isActive && !item.completed && thinkingDots(),
    item.completed && createElement('span', { class: 'thinking-checkmark' }, ['✓']),
  ]);
}

/**
 * What a live trace item's markup depends on: an unchanged key renders the
 * same item (so the update can be skipped).
 */
function traceItemKey(item: ThinkingTraceItem, isActive: boolean, isCurrent: boolean): unknown[] {
  const { type, label, detail, completed, metadata } = item;
  return [type, label, detail, completed, metadata?.icon, metadata?.label, metadata?.label_past, isActive, isCurrent];
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
  // After the toggle above: it reads the tapped node before the held update lands
  holdUpdatesWhilePressed(container);
  return container;
}

const LIVE_EXPANDED_CLASS = 'live-expanded';
// A tap whose click never comes (a drag) still releases the held update
const PRESS_RELEASE_FALLBACK_MS = 400;

/** A live trace, built, and the key of what it shows. */
interface LiveTrace {
  key: string;
  trace: HTMLElement;
}

// Pressed live lines and the trace held back while pressed. WebKit fires no
// click when the pressed node is replaced before the finger lifts, and every
// thinking event re-rendered the line: taps were lost (Oct 2026)
const pressedLines = new WeakSet<HTMLElement>();
const heldTrace = new WeakMap<HTMLElement, LiveTrace>();
// Key of the trace last written: an event that changes nothing is skipped
const renderedTraceKey = new WeakMap<HTMLElement, string>();

function holdUpdatesWhilePressed(container: HTMLElement): void {
  const release = (): void => {
    pressedLines.delete(container);
    const held = heldTrace.get(container);
    heldTrace.delete(container);
    // The answer may have started meanwhile: never write the live trace
    // into the finished summary
    const content = container.querySelector('.thinking-indicator-content');
    if (held !== undefined && content && !container.classList.contains('finalized')) {
      writeTrace(container, content, held);
    }
  };
  let fallback: number | undefined;
  container.addEventListener('pointerdown', () => {
    window.clearTimeout(fallback);
    pressedLines.add(container);
  });
  container.addEventListener('pointercancel', release);
  container.addEventListener('pointerup', () => {
    fallback = window.setTimeout(release, PRESS_RELEASE_FALLBACK_MS);
  });
  container.addEventListener('click', release);
}

/** The live (streaming) markup: the expand control and the trace. */
function renderLiveSkeleton(container: HTMLElement): void {
  container.classList.remove('finalized');
  renderedTraceKey.delete(container);
  const expanded = container.classList.contains(LIVE_EXPANDED_CLASS);
  const expand = createElement('button', {
    class: 'thinking-live-expand',
    type: 'button',
    'aria-expanded': String(expanded),
    'aria-label': 'Show the full trace',
  });
  setIcon(expand, CHEVRON_RIGHT_ICON);
  const dots = thinkingDots();
  container.replaceChildren(
    expand,
    createElement('div', { class: 'thinking-indicator-content' }, [
      createElement('div', { class: 'thinking-trace' }, [
        createElement('div', { class: 'thinking-trace-item active current' }, [
          createIconElement('thinking-icon', BRAIN_ICON),
          createElement('span', { class: 'thinking-label' }, ['Thinking']),
          dots,
        ]),
      ]),
    ])
  );
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
    const line = lines[i] ?? '';
    const heading = /^(?:\*\*|__)(.+?)(?:\*\*|__):?$/.exec(line) ?? /^#{1,6}\s+(.+)$/.exec(line);
    const title = heading?.[1];
    if (title !== undefined) return title.trim();
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

  const current = currentTraceIndex(state);
  // Thinking item is active if isThinking is true and no tool is active
  // Tool item is active if it matches the currently active tool and is not completed
  const items = state.trace.map((item, i) => ({
    item,
    isActive:
      item.type === 'thinking' ? state.isThinking && !state.activeTool : state.activeTool === item.label && !item.completed,
    isCurrent: i === current,
  }));
  // Empty trace while thinking: the initial thinking line
  const initial = items.length === 0 && state.isThinking;
  const key = JSON.stringify([initial, items.map((t) => traceItemKey(t.item, t.isActive, t.isCurrent))]);
  if (!pressedLines.has(container) && renderedTraceKey.get(container) === key) return;

  const trace = createElement(
    'div',
    { class: 'thinking-trace' },
    initial
      ? [
          createElement('div', { class: 'thinking-trace-item active current' }, [
            createIconElement('thinking-icon', BRAIN_ICON),
            createElement('span', { class: 'thinking-label' }, ['Thinking']),
            thinkingDots(),
          ]),
        ]
      : items.map((t) => traceItem(t.item, t.isActive, false, t.isCurrent))
  );
  if (pressedLines.has(container)) {
    heldTrace.set(container, { key, trace });
  } else {
    writeTrace(container, content, { key, trace });
  }
}

function writeTrace(container: HTMLElement, content: Element, live: LiveTrace): void {
  content.replaceChildren(live.trace);
  renderedTraceKey.set(container, live.key);
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
 * The finalized view's trace: rendered detail rows and the steps the summary
 * names (the same ones). Thinking comes first, then tools.
 */
function finalizedTrace(state: ThinkingState): { traceItems: HTMLElement[]; summaryItems: ThinkingTraceItem[] } {
  // Reorder trace for finalized view: thinking first, then tools (logical reading order)
  // During streaming, thinking is at the end for auto-scroll, but for reading it makes sense first
  const reorderedTrace = [
    ...state.trace.filter(item => item.type === 'thinking'),
    ...state.trace.filter(item => item.type === 'tool'),
  ];

  // Pass showFullDetail=true to show full text in finalized view
  const traceItems = reorderedTrace.map((item) => traceItem({ ...item, completed: true }, false, true));
  // The summary names the same steps the details list
  const summaryItems: ThinkingTraceItem[] = [...reorderedTrace];
  if (traceItems.length > 0) return { traceItems, summaryItems };

  // If no trace but we have thinking text or completed tools, build from those
  if (state.thinkingText) {
    const thinking: ThinkingTraceItem = { type: 'thinking', label: 'thinking', detail: state.thinkingText, completed: true };
    traceItems.push(traceItem(thinking, false, true));
    summaryItems.push(thinking);
  }
  for (const tool of state.completedTools) {
    const item: ThinkingTraceItem = { type: 'tool', label: tool, completed: true };
    traceItems.push(traceItem(item, false, true));
    summaryItems.push(item);
  }
  return { traceItems, summaryItems };
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

  const { traceItems, summaryItems } = finalizedTrace(state);

  // Collapsing the expanded trace shrinks content ABOVE anything the user is
  // reading further down - without compensation their reading position jumps
  // up by the collapsed height. Measure before/after and put it back.
  const scrollContainer = document.getElementById('messages');
  const heightBefore = container.offsetHeight;

  // Opened by the user while live: stays open
  const expanded = container.classList.contains(LIVE_EXPANDED_CLASS);
  container.classList.toggle('expanded', expanded);

  // Create collapsible structure
  const toggleButton = createElement('button', { class: 'thinking-toggle', 'aria-expanded': String(expanded), type: 'button' }, [
    createIconElement('thinking-toggle-icon', CHEVRON_RIGHT_ICON),
    createElement('span', { class: 'thinking-toggle-summary' }, [summarizeTrace(summaryItems)]),
  ]);
  const detailsEl = createElement('div', { class: 'thinking-details' }, [
    createElement('div', { class: 'thinking-trace' }, traceItems),
  ]);
  detailsEl.hidden = !expanded;
  container.replaceChildren(toggleButton, detailsEl);

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
  const thinkingItem = state.trace[thinkingIndex];
  if (thinkingItem) {
    thinkingItem.completed = true;
  }

  // Create the new tool item with metadata for display
  const toolItem: ThinkingTraceItem = {
    type: 'tool',
    label: tool,
    detail,
    completed: false,
    ...(metadata && { metadata }),
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
