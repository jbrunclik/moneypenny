/**
 * Conversation compaction indicator.
 *
 * Long regular conversations are compacted before being sent to the model:
 * older messages are replaced by a running summary (see
 * src/agent/conversation_compaction.py). The full history stays visible in the
 * UI, so without this indicator nothing tells the user the model no longer
 * sees those messages verbatim.
 *
 * Surfaces:
 * - a header chip (desktop chat header + mobile header): "48/72 · ×4"
 * - a divider in #messages after the last summarized message, with the
 *   summarized messages dimmed (opacity only - no layout-affecting effects)
 * - a popup with the depth stats and the summary text the model sees
 */

import { beginProgrammaticScroll, endProgrammaticScroll } from '../utils/programmatic-scroll';
import { costs } from '../api/costs';
import { COMPACTION_DEEP_GENERATION } from '../config';
import { useStore } from '../state/store';
import type { ConversationCompactionResponse } from '../types/api';
import { createElement, getElementById, isScrolledToBottom, setSanitizedHtml } from '../utils/dom';
import { COMPACTION_ICON, setIcon } from '../utils/icons';
import { renderMarkdown } from '../utils/markdown';
import { createPopup, createPopupHtml, type PopupInstance } from './InfoPopup';

const POPUP_ID = 'compaction-popup';
const EVENT_NAME = 'compaction:open';
const CHIP_IDS = ['conversation-compaction', 'conversation-compaction-mobile'];
const DIVIDER_CLASS = 'compaction-divider';
const COMPACTED_CLASS = 'message--compacted';
const DEEP_CLASS = 'compaction--deep';

/** Last active status, only while it belongs to the open conversation */
let currentStatus: ConversationCompactionResponse | null = null;

/** The cached status, dropped once another conversation is open */
function statusForOpenConversation(): ConversationCompactionResponse | null {
  if (currentStatus?.conversation_id !== useStore.getState().currentConversation?.id) {
    currentStatus = null;
  }
  return currentStatus;
}

function isDeep(status: ConversationCompactionResponse): boolean {
  return status.generation >= COMPACTION_DEEP_GENERATION;
}

function generationLabel(status: ConversationCompactionResponse): string {
  return `${status.generation_estimated ? '~' : ''}${status.generation}`;
}

function compactionDetails(status: ConversationCompactionResponse): HTMLElement[] {
  const verbatim = status.total_count - status.summarized_count;
  const passes = generationLabel(status);
  const lossNote = isDeep(status)
    ? 'The oldest messages have been condensed several times, so early specifics are likely lost. ' +
      'The assistant can still search them for exact details.'
    : 'A summary keeps the gist, not every detail. The assistant can still search the ' +
      'summarized messages for exact details.';
  const summary = createElement('div', { class: 'compaction-summary markdown-body' });
  if (status.summary) setSanitizedHtml(summary, renderMarkdown(status.summary));
  const row = (label: string, value: string): HTMLTableRowElement =>
    createElement('tr', {}, [
      createElement('td', { class: 'compaction-label' }, [label]),
      createElement('td', { class: 'compaction-value' }, [value]),
    ]);
  return [
    createElement('div', { class: 'compaction-content' }, [
      createElement('table', { class: 'compaction-table' }, [
        createElement('tbody', {}, [
          row('Summarized', `${status.summarized_count} of ${status.total_count} messages`),
          row('Summary passes', `${passes}${status.generation_estimated ? ' (estimated)' : ''}`),
          row('Sent verbatim', `last ${verbatim} messages`),
        ]),
      ]),
      createElement('p', { class: `compaction-note${isDeep(status) ? ` ${DEEP_CLASS}` : ''}` }, [lossNote]),
      createElement('h4', { class: 'compaction-summary-heading' }, ['What the model remembers']),
      summary,
    ]),
  ];
}

const compactionPopup: PopupInstance<ConversationCompactionResponse> = createPopup(
  {
    id: POPUP_ID,
    eventName: EVENT_NAME,
    icon: COMPACTION_ICON,
    title: 'Conversation Compaction',
    styleClass: 'compaction',
  },
  compactionDetails
);

/** HTML shell for the popup (embedded in the app shell by core/startup/app-shell.ts) */
export function getCompactionPopupHtml(): string {
  return createPopupHtml(POPUP_ID);
}

function openCompactionPopup(): void {
  const status = statusForOpenConversation();
  if (status) compactionPopup.open(status);
}

/** Initialize popup handlers and delegated clicks on the chip/divider */
export function initCompactionIndicator(): void {
  compactionPopup.init();
  // Delegated: the desktop chip is re-created whenever the chat header
  // re-renders, and the divider whenever messages re-render.
  document.addEventListener('click', (e) => {
    const target = e.target as HTMLElement | null;
    if (target?.closest(`.chat-header-compaction, .${DIVIDER_CLASS}`)) {
      openCompactionPopup();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const target = e.target as HTMLElement | null;
    if (target?.classList.contains(DIVIDER_CLASS)) {
      e.preventDefault();
      openCompactionPopup();
    }
  });
}

function renderChips(): void {
  const status = statusForOpenConversation();
  for (const id of CHIP_IDS) {
    const chip = getElementById<HTMLElement>(id);
    if (!chip) continue;
    if (!status) {
      chip.classList.add('hidden');
      chip.textContent = '';
      continue;
    }
    chip.classList.remove('hidden');
    chip.classList.toggle(DEEP_CLASS, isDeep(status));
    // Counts collapse on mobile, where the header only fits the depth
    setIcon(chip, COMPACTION_ICON);
    chip.append(
      createElement('span', { class: 'compaction-chip-counts' }, [`${status.summarized_count}/${status.total_count} · `]),
      createElement('span', {}, [`×${generationLabel(status)}`])
    );
    const label =
      `${status.summarized_count} of ${status.total_count} messages are summarized for the model ` +
      `(${generationLabel(status)} summary passes)`;
    chip.title = label;
    chip.setAttribute('aria-label', label);
  }
}

function buildDivider(status: ConversationCompactionResponse): HTMLElement {
  const divider = document.createElement('div');
  divider.className = DIVIDER_CLASS;
  divider.classList.toggle(DEEP_CLASS, isDeep(status));
  divider.setAttribute('role', 'button');
  divider.setAttribute('tabindex', '0');
  const label = createElement('span', { class: 'compaction-divider-label' });
  setIcon(label, COMPACTION_ICON);
  label.appendChild(
    createElement('span', {}, [
      `${status.summarized_count} messages above summarized`,
      createElement('span', { class: 'compaction-divider-detail' }, [' for the model']),
      ` · ×${generationLabel(status)} · View`,
    ])
  );
  divider.append(
    createElement('span', { class: 'compaction-divider-line' }),
    label,
    createElement('span', { class: 'compaction-divider-line' })
  );
  return divider;
}

/** First message whose bottom edge is below the container's top edge */
function findScrollAnchor(container: HTMLElement): HTMLElement | null {
  const top = container.getBoundingClientRect().top;
  for (const el of container.querySelectorAll<HTMLElement>('.message')) {
    if (el.getBoundingClientRect().bottom > top) return el;
  }
  return null;
}

/**
 * Clear the divider and dimming, then mark the open conversation's boundary
 * again. Returns whether there was a divider before or after.
 */
function replaceCompactionMarkers(container: HTMLElement): boolean {
  const hadDivider = container.querySelector(`.${DIVIDER_CLASS}`) !== null;
  container.querySelectorAll(`.${DIVIDER_CLASS}`).forEach((el) => el.remove());
  container.querySelectorAll(`.${COMPACTED_CLASS}`).forEach((el) => {
    el.classList.remove(COMPACTED_CLASS);
  });

  const status = statusForOpenConversation();
  const boundary = status?.boundary_message_id
    ? container.querySelector<HTMLElement>(`.message[data-message-id="${status.boundary_message_id}"]`)
    : null;
  if (!status || !boundary) return hadDivider;
  for (const el of container.querySelectorAll<HTMLElement>('.message')) {
    el.classList.add(COMPACTED_CLASS);
    if (el === boundary) break;
  }
  boundary.after(buildDivider(status));
  return true;
}

/**
 * Place the divider after the boundary message and dim everything up to it.
 *
 * Idempotent - safe to call after any (re-)render.
 *
 * @param options.preserveScroll - #messages opts out of browser scroll
 *   anchoring (overflow-anchor: none), so inserting or moving the divider
 *   shifts the visible content. When set, the position is restored: pinned to
 *   the bottom if the user was following, otherwise kept on the first visible
 *   message. Callers that already manage scroll around their own DOM changes
 *   (full render, pagination prepend) leave it off.
 */
export function applyCompactionMarkers(
  container: HTMLElement | null = getElementById('messages'),
  options: { preserveScroll?: boolean } = {}
): void {
  if (!container) return;
  const preserve = options.preserveScroll ?? false;
  // Really at the bottom, not the 200px "following" zone: a send-to-top turn
  // sits at its reserved bottom, and a reply that ran a little past the
  // screen was yanked down to its end by the pin below
  const wasAtBottom = preserve && isScrolledToBottom(container, 1);
  const anchor = preserve && !wasAtBottom ? findScrollAnchor(container) : null;
  const anchorTop = anchor?.getBoundingClientRect().top ?? 0;

  // No divider before or after: nothing moved, so leave the scroll alone
  // (this runs after every turn)
  if (!replaceCompactionMarkers(container)) return;

  if (wasAtBottom) {
    endProgrammaticScroll(beginProgrammaticScroll()); // ours, not the user's scroll
    container.scrollTop = container.scrollHeight;
  } else if (anchor) {
    endProgrammaticScroll(beginProgrammaticScroll()); // ours, not the user's scroll
    container.scrollTop += anchor.getBoundingClientRect().top - anchorTop;
  }
}

/**
 * Fetch and render the compaction state of a conversation (null clears it).
 * Refreshed wherever the conversation cost chip refreshes.
 */
export async function updateCompactionIndicator(convId: string | null): Promise<void> {
  if (!convId) {
    currentStatus = null;
    renderChips();
    applyCompactionMarkers(undefined, { preserveScroll: true });
    return;
  }

  let status: ConversationCompactionResponse | null;
  try {
    const response = await costs.getConversationCompaction(convId);
    status = response.active ? response : null;
  } catch {
    // Indicator is informational - hide it rather than surface an error
    status = null;
  }

  // The user may have switched conversations while the request was in flight
  if (useStore.getState().currentConversation?.id !== convId) return;
  currentStatus = status;
  renderChips();
  applyCompactionMarkers(undefined, { preserveScroll: true });
}
