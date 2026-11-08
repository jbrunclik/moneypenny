/**
 * The quiet "Memory updated: ..." line under a reply the background memory
 * review learned from. A click opens Memories (the Data page; delegated in
 * core/events.ts). The merge patches it into a reply already on screen.
 */
import { createElement } from '../../utils/dom';
import { BRAIN_ICON, createIconElement } from '../../utils/icons';

const MEMORY_NOTE_CLASS = 'message-memory-note';

export function renderMemoryNote(note: string): HTMLElement {
  return createElement('button', { class: MEMORY_NOTE_CLASS, type: 'button', title: 'Open Memories' }, [
    createIconElement('message-memory-note-icon', BRAIN_ICON),
    createElement('span', { class: 'message-memory-note-text' }, [`Memory updated: ${note}`]),
  ]);
}

/** Show `note` under a rendered reply, replacing any older one. */
export function setMemoryNote(messageEl: HTMLElement, note: string): void {
  const wrapper = messageEl.querySelector<HTMLElement>('.message-content-wrapper');
  if (!wrapper) return;
  const next = renderMemoryNote(note);
  const existing = wrapper.querySelector(`:scope > .${MEMORY_NOTE_CLASS}`);
  if (existing) {
    existing.replaceWith(next);
    return;
  }
  const content = wrapper.querySelector(':scope > .message-content');
  if (content) content.after(next);
  else wrapper.appendChild(next);
}
