/**
 * A user message the app sent on the user's behalf (Look it up, starting a
 * deep-research run) renders as a quiet row instead of a typed bubble:
 * what it did, and a ↑ link back to the claim or offer it came from.
 */
import { CLAIM_FLASH_MS } from '../../config';
import { useStore } from '../../state/store';
import type { Message, MessageAction } from '../../types/api';
import { prefersReducedMotion } from '../../utils/dom';
import { SEARCH_ICON, SPARKLES_ICON } from '../../utils/icons';
import { applySendState } from './send-state';

const ROW_CLASS = 'message--action';
const wired = new WeakSet<HTMLElement>();

function sourceId(action: MessageAction): string | null {
  return action.type === 'verify_claim' ? action.source_message_id : action.offer_message_id;
}

/** The source is linkable only when it is a loaded message of this conversation. */
function sourceLoaded(id: string | null): boolean {
  if (!id) return false;
  const convId = useStore.getState().currentConversation?.id;
  return Boolean(convId && useStore.getState().getMessages(convId).some((m) => m.id === id));
}

function rowText(action: MessageAction): string {
  if (action.type === 'verify_claim') return `Looking up “${action.quote}”`;
  const parts = ['Deep research started', `${action.items} ${action.items === 1 ? 'question' : 'questions'}`];
  if (action.minutes) parts.push(`~${action.minutes}\u00a0min`); // NBSP: "~5 min" never splits across lines
  return parts.join(' · ');
}

export function addActionRowToUI(message: Message, container: HTMLElement, options?: { animate?: boolean }): void {
  const action = message.action!;
  const messageEl = document.createElement('div');
  messageEl.className = `message user ${ROW_CLASS}`;
  messageEl.dataset.messageId = message.id;
  if (options?.animate) {
    messageEl.classList.add('message--entering');
    messageEl.addEventListener('animationend', () => messageEl.classList.remove('message--entering'), { once: true });
  }

  const wrapper = document.createElement('div');
  wrapper.className = 'message-content-wrapper';
  const rowEl = document.createElement('div');
  rowEl.className = 'action-row';
  const icon = document.createElement('span');
  icon.className = 'action-row__icon';
  icon.innerHTML = action.type === 'verify_claim' ? SEARCH_ICON : SPARKLES_ICON;
  const text = document.createElement('span');
  text.className = 'action-row__text';
  text.textContent = rowText(action);
  rowEl.append(icon, text);
  const source = sourceId(action);
  if (sourceLoaded(source)) {
    const link = document.createElement('button');
    link.type = 'button';
    link.className = 'action-row__source';
    link.dataset.sourceId = source!;
    if (action.type === 'verify_claim' && action.claim_index !== null) link.dataset.claim = String(action.claim_index);
    link.textContent = action.type === 'verify_claim' ? 'from the answer above ↑' : 'from the offer above ↑';
    rowEl.append(link);
  }
  wrapper.appendChild(rowEl);
  applySendState(messageEl, wrapper, message.id, message.status);
  messageEl.appendChild(wrapper);
  container.appendChild(messageEl);
}

/** Scroll to an element and flash it for CLAIM_FLASH_MS. */
export function flashElement(target: HTMLElement, flashClass: string): void {
  target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
  target.classList.add(flashClass);
  window.setTimeout(() => target.classList.remove(flashClass), CLAIM_FLASH_MS);
}

function onClick(e: Event): void {
  const link = (e.target as Element).closest<HTMLButtonElement>('.action-row__source');
  if (!link?.dataset.sourceId) return;
  const source = document.querySelector<HTMLElement>(`.message[data-message-id="${link.dataset.sourceId}"]`);
  if (!source) return;
  const claim = link.dataset.claim ? source.querySelector<HTMLElement>(`[data-claim="${link.dataset.claim}"]`) : null;
  if (claim) flashElement(claim, 'claim--flash');
  else flashElement(source, 'message--flash');
}

/** Delegated ↑ links on the message list (call once it exists). */
export function initActionRows(container = document.getElementById('messages')): void {
  if (!container || wired.has(container)) return;
  wired.add(container);
  container.addEventListener('click', onClick);
}
