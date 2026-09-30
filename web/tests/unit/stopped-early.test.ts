/**
 * Replies cut off by the tool-round cap show a note with a Continue button.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { appendStoppedEarlyNote } from '@/components/messages/stopped-early';

function wrapper(): HTMLElement {
  document.body.innerHTML = `
    <div class="message assistant" data-message-id="m1">
      <div class="message-content-wrapper">
        <div class="message-content">Partial answer</div>
        <div class="message-actions"></div>
      </div>
    </div>`;
  return document.querySelector<HTMLElement>('.message-content-wrapper')!;
}

describe('appendStoppedEarlyNote', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('inserts the note between the content and the actions', () => {
    const el = wrapper();
    appendStoppedEarlyNote(el, 'm1');

    const note = el.querySelector('.message-stopped-early');
    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('may be incomplete');
    expect(note?.nextElementSibling?.classList.contains('message-actions')).toBe(true);
  });

  it('is idempotent', () => {
    const el = wrapper();
    appendStoppedEarlyNote(el, 'm1');
    appendStoppedEarlyNote(el, 'm1');
    expect(el.querySelectorAll('.message-stopped-early')).toHaveLength(1);
  });

  it('Continue dispatches the existing continue re-run for that message', () => {
    const el = wrapper();
    const handler = vi.fn();
    document.addEventListener('message:continue', handler);
    appendStoppedEarlyNote(el, 'm1');

    el.querySelector<HTMLButtonElement>('.message-stopped-early-continue')!.click();

    expect(handler).toHaveBeenCalledTimes(1);
    expect((handler.mock.calls[0][0] as CustomEvent).detail).toEqual({ messageId: 'm1' });
    document.removeEventListener('message:continue', handler);
  });

  it('appends at the end when the actions are not rendered yet', () => {
    document.body.innerHTML = '<div class="message-content-wrapper"><div class="message-content"></div></div>';
    const el = document.querySelector<HTMLElement>('.message-content-wrapper')!;
    appendStoppedEarlyNote(el, 'm1');
    expect(el.lastElementChild?.classList.contains('message-stopped-early')).toBe(true);
  });

  it('labels a user stop as stopped, still offering Continue', () => {
    const el = wrapper();
    appendStoppedEarlyNote(el, 'm1', 'user');
    const note = el.querySelector('.message-stopped-early');
    expect(note?.textContent).toContain('Stopped.');
    expect(note?.textContent).not.toContain('tool-step limit');
    expect(el.querySelector('.message-stopped-early-continue')).not.toBeNull();
  });
});
