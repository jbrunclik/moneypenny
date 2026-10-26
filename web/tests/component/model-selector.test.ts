/**
 * Model selector: the dropdown lists the models with a check on the one in
 * use (the conversation's, else the pending pick, else the default) and the
 * button shows its short name. Picking a model updates the button at once;
 * with no conversation it becomes the pending model, a temp conversation
 * changes locally, a saved one is updated on the server and rolls the
 * button back with a toast when that fails. The button opens the list with
 * a click or the arrow keys, which then move a highlight (wrapping) that
 * Enter selects; Escape and outside clicks close it.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import type { Conversation, Model } from '@/types/api';

const api = vi.hoisted(() => ({ update: vi.fn<(id: string, data: { model: string }) => Promise<unknown>>() }));
const toastMock = vi.hoisted(() => ({ error: vi.fn() }));

vi.mock('@/api/conversations', () => ({ conversations: api }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));

import { useStore } from '@/state/store';
import { initModelSelector, renderModelDropdown } from '@/components/ModelSelector';

const MODELS: Model[] = [
  { id: 'fast', name: 'Gemini Flash', short_name: 'Flash', description: 'Quick answers' },
  { id: 'smart', name: 'Gemini Pro', short_name: 'Pro' },
  { id: 'tiny', name: 'Gemini <Lite>', short_name: 'Lite & co' },
];

function conv(id: string, model = 'fast'): Conversation {
  return { id, title: 't', model, created_at: '', updated_at: '' };
}

const dropdown = (): HTMLElement => document.getElementById('model-dropdown') as HTMLElement;
const button = (): HTMLElement => document.getElementById('model-selector-btn') as HTMLElement;
const buttonLabel = (): string | null | undefined => document.getElementById('current-model-name')?.textContent;
const option = (id: string): HTMLElement => dropdown().querySelector(`[data-model-id="${id}"]`) as HTMLElement;
const selectedIds = (): string[] =>
  Array.from(dropdown().querySelectorAll<HTMLElement>('.model-option.selected')).map((o) => o.dataset.modelId ?? '');
const focusedId = (): string | undefined =>
  dropdown().querySelector<HTMLElement>('.model-option.focused')?.dataset.modelId;
const isOpen = (): boolean => !dropdown().classList.contains('hidden');

function key(k: string): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
  button().dispatchEvent(event);
  return event;
}

describe('ModelSelector', () => {
  // The app wires the selector once at startup (its outside-click listener
  // lives on document), so the elements persist and only their state resets
  beforeAll(() => {
    document.body.innerHTML = `
      <button id="model-selector-btn"><span id="current-model-name"></span></button>
      <div id="model-dropdown" class="hidden"></div>
      <div id="outside"></div>`;
    initModelSelector();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState(useStore.getInitialState(), true);
    useStore.setState({ models: MODELS, defaultModel: 'fast' });
    dropdown().innerHTML = '';
    dropdown().classList.add('hidden');
    button().setAttribute('aria-expanded', 'false');
    const label = document.getElementById('current-model-name');
    if (label) label.textContent = '';
  });

  describe('renderModelDropdown', () => {
    it('lists every model and checks the default when nothing else is chosen', () => {
      renderModelDropdown();
      expect(dropdown().querySelectorAll('.model-option')).toHaveLength(3);
      expect(selectedIds()).toEqual(['fast']);
      expect(option('fast').getAttribute('aria-selected')).toBe('true');
      expect(option('fast').querySelector('.model-check')).not.toBeNull();
      expect(option('smart').querySelector('.model-check')).toBeNull();
      expect(buttonLabel()).toBe('Flash');
    });

    it("prefers the conversation's model over the pending pick and the default", () => {
      useStore.setState({ pendingModel: 'tiny' });
      renderModelDropdown();
      expect(selectedIds()).toEqual(['tiny']);

      useStore.getState().setCurrentConversation(conv('c1', 'smart'));
      renderModelDropdown();
      expect(selectedIds()).toEqual(['smart']);
      expect(buttonLabel()).toBe('Pro');
    });

    it('shows the description next to the name, and escapes model text', () => {
      renderModelDropdown();
      expect(option('fast').querySelector('.model-option-desc')?.textContent).toBe('Gemini Flash · Quick answers');
      expect(option('tiny').querySelector('.model-option-desc')?.textContent).toBe('Gemini <Lite>');
      expect(option('tiny').querySelector('.model-name')?.textContent).toBe('Lite & co');
      expect(option('tiny').querySelector('lite')).toBeNull();
    });
  });

  describe('selecting a model', () => {
    beforeEach(() => {
      renderModelDropdown();
    });

    it('without a conversation, becomes the pending model', () => {
      option('smart').click();
      expect(useStore.getState().pendingModel).toBe('smart');
      expect(buttonLabel()).toBe('Pro');
      expect(api.update).not.toHaveBeenCalled();
    });

    it('for a temp conversation, changes the model locally only', () => {
      useStore.getState().addConversation(conv('temp-1'));
      useStore.getState().setCurrentConversation(conv('temp-1'));
      option('smart').click();
      expect(useStore.getState().currentConversation?.model).toBe('smart');
      expect(useStore.getState().conversations[0]?.model).toBe('smart');
      expect(api.update).not.toHaveBeenCalled();
    });

    it('for a saved conversation, updates the server and then the store', async () => {
      api.update.mockResolvedValue({});
      useStore.getState().addConversation(conv('c1'));
      useStore.getState().setCurrentConversation(conv('c1'));
      option('smart').click();

      expect(api.update).toHaveBeenCalledWith('c1', { model: 'smart' });
      await vi.waitFor(() => expect(useStore.getState().currentConversation?.model).toBe('smart'));
      expect(buttonLabel()).toBe('Pro');
    });

    it('rolls the button back and toasts when the server update fails', async () => {
      api.update.mockRejectedValue(new Error('500'));
      useStore.getState().setCurrentConversation(conv('c1', 'fast'));
      option('smart').click();
      expect(buttonLabel()).toBe('Pro');

      await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to change model. Please try again.'));
      expect(buttonLabel()).toBe('Flash');
      expect(useStore.getState().currentConversation?.model).toBe('fast');
    });

    it('closes the dropdown after a pick', () => {
      button().click();
      expect(isOpen()).toBe(true);
      option('smart').click();
      expect(isOpen()).toBe(false);
      expect(button().getAttribute('aria-expanded')).toBe('false');
    });

    it('ignores an id the model list does not know', () => {
      dropdown().insertAdjacentHTML('beforeend', '<div class="model-option" data-model-id="gone"></div>');
      option('gone').click();
      expect(useStore.getState().pendingModel).toBeNull();
      expect(buttonLabel()).toBe('Flash');
    });
  });

  describe('opening and keyboard', () => {
    it('sets up the listbox roles', () => {
      expect(button().getAttribute('aria-haspopup')).toBe('listbox');
      expect(dropdown().getAttribute('role')).toBe('listbox');
    });

    it('opens on click with a fresh check mark, and closes on an outside click', () => {
      useStore.setState({ pendingModel: 'smart' });
      button().click();
      expect(isOpen()).toBe(true);
      expect(button().getAttribute('aria-expanded')).toBe('true');
      expect(selectedIds()).toEqual(['smart']);

      document.getElementById('outside')?.click();
      expect(isOpen()).toBe(false);
    });

    it('stays open on a click inside the list that misses an option', () => {
      button().click();
      dropdown().click();
      expect(isOpen()).toBe(true);
    });

    it('opens with ArrowDown on the first option and ArrowUp on the last', () => {
      key('ArrowDown');
      expect(isOpen()).toBe(true);
      expect(focusedId()).toBe('fast');

      key('Escape');
      expect(isOpen()).toBe(false);
      const event = key('ArrowUp');
      expect(event.defaultPrevented).toBe(true);
      expect(focusedId()).toBe('tiny');
    });

    it('moves the highlight with wrap-around and selects it with Enter', () => {
      key('ArrowDown');
      key('ArrowDown');
      expect(focusedId()).toBe('smart');
      key('ArrowDown');
      key('ArrowDown');
      expect(focusedId()).toBe('fast');
      key('ArrowUp');
      expect(focusedId()).toBe('tiny');

      const event = key('Enter');
      expect(event.defaultPrevented).toBe(true);
      expect(useStore.getState().pendingModel).toBe('tiny');
      expect(isOpen()).toBe(false);
    });

    it('ignores Enter while closed or with nothing highlighted', () => {
      expect(key('Enter').defaultPrevented).toBe(false);
      button().click();
      expect(key('Enter').defaultPrevented).toBe(false);
      expect(useStore.getState().pendingModel).toBeNull();
    });
  });
});
