/**
 * The note on a reply the backup model wrote (messages/model-fallback-note.ts):
 * names both models, sits above the actions, and Retry re-runs the turn.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '@/state/store';
import {
  appendModelFallbackNote,
  modelFallbackText,
  showModelFallbackNote,
} from '@/components/messages/model-fallback-note';

function setConversationModel(model: string): void {
  useStore.setState({
    models: [
      { id: 'gemini-4-hydrogen', name: 'Gemini 4 Hydrogen', short_name: 'Fast' },
      { id: 'gemini-4-carbon', name: 'Gemini 4 Carbon', short_name: 'Advanced' },
    ],
    currentConversation: { id: 'c1', title: 't', model, created_at: '', updated_at: '' },
  } as never);
}

function reply(id = 'm1'): { messageEl: HTMLElement; wrapper: HTMLElement } {
  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant';
  messageEl.dataset.messageId = id;
  const wrapper = document.createElement('div');
  wrapper.className = 'message-content-wrapper';
  const content = document.createElement('div');
  content.className = 'message-content';
  const actions = document.createElement('div');
  actions.className = 'message-actions';
  wrapper.append(content, actions);
  messageEl.appendChild(wrapper);
  return { messageEl, wrapper };
}

describe('model fallback note', () => {
  beforeEach(() => {
    setConversationModel('gemini-4-carbon');
  });

  it('names the model that did not answer and the one that did', () => {
    expect(modelFallbackText('gemini-4-hydrogen')).toBe(
      "Advanced wasn't responding, so Fast answered instead."
    );
  });

  it('still reads right once the chat was switched to the fallback model', () => {
    setConversationModel('gemini-4-hydrogen');
    expect(modelFallbackText('gemini-4-hydrogen')).toBe(
      "The chat's model wasn't responding, so Fast answered instead."
    );
  });

  it('shows an unknown model by its id', () => {
    expect(modelFallbackText('gemini-other')).toBe(
      "Advanced wasn't responding, so gemini-other answered instead."
    );
  });

  it('sits above the actions, once', () => {
    const { wrapper } = reply();

    appendModelFallbackNote(wrapper, 'gemini-4-hydrogen');
    appendModelFallbackNote(wrapper, 'gemini-4-hydrogen');

    const notes = wrapper.querySelectorAll('.message-model-fallback');
    expect(notes).toHaveLength(1);
    expect(notes[0]?.nextElementSibling?.classList.contains('message-actions')).toBe(true);
    expect(notes[0]?.getAttribute('role')).toBe('note');
    expect(notes[0]?.textContent).toContain("Advanced wasn't responding");
  });

  it('goes at the end of a reply still streaming (no actions yet)', () => {
    const { messageEl, wrapper } = reply();
    wrapper.querySelector('.message-actions')?.remove();

    showModelFallbackNote(messageEl, 'gemini-4-hydrogen');

    expect(wrapper.lastElementChild?.classList.contains('message-model-fallback')).toBe(true);
  });

  it('Retry regenerates the reply by its id, read at click time', () => {
    const { messageEl, wrapper } = reply('');
    const regenerate = vi.fn();
    document.addEventListener('message:regenerate', regenerate);
    appendModelFallbackNote(wrapper, 'gemini-4-hydrogen');
    const retry = wrapper.querySelector<HTMLButtonElement>('.message-model-fallback-retry');

    retry?.click();
    expect(regenerate).not.toHaveBeenCalled();

    messageEl.dataset.messageId = 'm9';
    retry?.click();
    expect(regenerate).toHaveBeenCalledOnce();
    expect((regenerate.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({ messageId: 'm9' });
    document.removeEventListener('message:regenerate', regenerate);
  });
});
