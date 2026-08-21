/**
 * Send-state chrome for user messages: pending/failed classes and the
 * failed-message retry/discard affordance.
 *
 * Clicks dispatch `outbox:retry` / `outbox:discard` CustomEvents on document
 * (handled in core/messaging) so this component stays free of send logic.
 */
import { DELETE_ICON, REFRESH_ICON, WARNING_ICON } from '../../utils/icons';

export type SendState = 'pending' | 'failed' | 'sent';

const PENDING_CLASS = 'message--send-pending';
const FAILED_CLASS = 'message--send-failed';

function createActionButton(action: string, icon: string, label: string): HTMLButtonElement {
  const button = document.createElement('button');
  button.className = 'send-status-action';
  button.dataset.action = action;
  button.innerHTML = icon;
  button.appendChild(document.createTextNode(label));
  return button;
}

/** The "Not sent" row with retry/discard actions, appended below the bubble. */
export function createSendFailedActions(messageId: string): HTMLElement {
  const row = document.createElement('div');
  row.className = 'message-send-status';

  const label = document.createElement('span');
  label.className = 'send-status-label';
  label.innerHTML = WARNING_ICON;
  label.appendChild(document.createTextNode('Not sent'));
  row.appendChild(label);

  const retry = createActionButton('retry-send', REFRESH_ICON, 'Retry');
  const discard = createActionButton('discard-send', DELETE_ICON, 'Discard');
  row.appendChild(retry);
  row.appendChild(discard);

  row.addEventListener('click', (e) => {
    const button = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-action]');
    if (!button) return;
    const eventName = button.dataset.action === 'retry-send' ? 'outbox:retry' : 'outbox:discard';
    document.dispatchEvent(new CustomEvent(eventName, { detail: { messageId } }));
  });

  return row;
}

/** Apply send-state chrome to a freshly built message element. */
export function applySendState(
  messageEl: HTMLElement,
  contentWrapper: HTMLElement,
  messageId: string,
  status: 'pending' | 'failed' | undefined
): void {
  if (!status) return;
  if (status === 'pending') {
    messageEl.classList.add(PENDING_CLASS);
    return;
  }
  messageEl.classList.add(FAILED_CLASS);
  contentWrapper.appendChild(createSendFailedActions(messageId));
}

/** Transition an already-rendered message's send state in place. */
export function setMessageSendState(messageId: string, state: SendState): void {
  const messageEl = document.querySelector<HTMLElement>(`[data-message-id="${messageId}"]`);
  if (!messageEl) return;

  messageEl.classList.toggle(PENDING_CLASS, state === 'pending');
  messageEl.classList.toggle(FAILED_CLASS, state === 'failed');

  // Once the server has the message its blobs are fetchable - enable lightbox
  if (state === 'sent') {
    messageEl.querySelectorAll<HTMLImageElement>('img[data-pending]').forEach((img) => {
      delete img.dataset.pending;
    });
  }

  const existingRow = messageEl.querySelector('.message-send-status');
  if (state === 'failed' && !existingRow) {
    const contentWrapper = messageEl.querySelector<HTMLElement>('.message-content-wrapper');
    contentWrapper?.appendChild(createSendFailedActions(messageId));
  } else if (state !== 'failed' && existingRow) {
    existingRow.remove();
  }
}
