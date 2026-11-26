/**
 * Note on a reply the backup model wrote: the conversation's own model was
 * down or not answering (503, 504, timeout), so the other tier answered
 * (src/agent/chat_node.py fallback). The server saves it on the reply
 * (model_fallback), so the note stays after a reload and on other devices.
 * Retry re-runs the turn on the conversation's own model; CSS shows it only
 * on the latest finished reply, like Continue on the stopped-early note.
 */
import { useStore } from '../../state/store';
import { WARNING_ICON, setIcon } from '../../utils/icons';

const NOTE_CLASS = 'message-model-fallback';

function shortName(modelId: string | undefined): string | null {
  if (!modelId) return null;
  const model = useStore.getState().models.find((m) => m.id === modelId);
  return model?.short_name ?? modelId;
}

/** "Advanced wasn't responding, so Fast answered instead." */
export function modelFallbackText(toModelId: string): string {
  const to = shortName(toModelId) ?? toModelId;
  const fromId = useStore.getState().currentConversation?.model;
  const from = fromId && fromId !== toModelId ? shortName(fromId) : null;
  return from
    ? `${from} wasn't responding, so ${to} answered instead.`
    : `The chat's model wasn't responding, so ${to} answered instead.`;
}

/** Add the note to a reply's content wrapper, above its actions (idempotent). */
export function appendModelFallbackNote(contentWrapper: Element, toModelId: string): void {
  if (contentWrapper.querySelector(`.${NOTE_CLASS}`)) return;

  const note = document.createElement('div');
  note.className = NOTE_CLASS;
  note.setAttribute('role', 'note');
  const icon = document.createElement('span');
  icon.className = 'message-model-fallback-icon';
  icon.setAttribute('aria-hidden', 'true');
  setIcon(icon, WARNING_ICON);
  const text = document.createElement('span');
  text.className = 'message-model-fallback-text';
  text.textContent = modelFallbackText(toModelId);
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'message-model-fallback-retry';
  retry.textContent = 'Retry';
  retry.addEventListener('click', () => {
    // Read at click time: a streamed reply gets its id when it finishes
    const messageId = retry.closest<HTMLElement>('.message')?.dataset.messageId;
    if (!messageId) return;
    document.dispatchEvent(new CustomEvent('message:regenerate', { detail: { messageId } }));
  });
  note.append(icon, text, retry);

  const actions = contentWrapper.querySelector(':scope > .message-actions');
  if (actions) {
    contentWrapper.insertBefore(note, actions);
  } else {
    contentWrapper.appendChild(note);
  }
}

/** The note on a message element (live stream or finished reply). */
export function showModelFallbackNote(messageEl: HTMLElement, toModelId: string): void {
  const wrapper = messageEl.querySelector('.message-content-wrapper');
  if (wrapper) appendModelFallbackNote(wrapper, toModelId);
}
