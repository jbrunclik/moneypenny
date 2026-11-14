/**
 * The model dropdown is an HTML string: a model id must stay inside its
 * data attribute (F3).
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { useStore } from '@/state/store';
import { renderModelDropdown } from '@/components/ModelSelector';
import type { Model } from '@/types/api';

describe('renderModelDropdown', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="model-dropdown"></div>';
  });

  it('keeps a model id with quotes inside its attribute', () => {
    const id = 'm1" data-evil="1';
    useStore.setState({
      models: [{ id, name: 'Model', short_name: 'M' } as Model],
      currentConversation: null,
      pendingModel: null,
      defaultModel: id,
    });

    renderModelDropdown();

    expect(document.querySelector('[data-evil]')).toBeNull();
    const option = document.querySelector<HTMLElement>('.model-option');
    expect(option?.dataset.modelId).toBe(id);
    expect(option?.classList.contains('selected')).toBe(true);
  });

  describe('with a single model', () => {
    beforeEach(() => {
      document.body.innerHTML =
        '<div class="model-selector"><button id="model-selector-btn"><span id="current-model-name"></span></button><div id="model-dropdown"></div></div>';
    });

    const picker = () => document.querySelector<HTMLElement>('.model-selector');
    const models = (n: number) =>
      Array.from({ length: n }, (_, i) => ({ id: `m${i}`, name: `Model ${i}`, short_name: `M${i}` }) as Model);

    it('hides the picker when only one model is offered', () => {
      useStore.setState({ models: models(1), currentConversation: null, pendingModel: null, defaultModel: 'm0' });
      renderModelDropdown();
      expect(picker()?.classList.contains('hidden')).toBe(true);
    });

    it('shows the picker again once there is a choice', () => {
      useStore.setState({ models: models(1), currentConversation: null, pendingModel: null, defaultModel: 'm0' });
      renderModelDropdown();
      useStore.setState({ models: models(2) });
      renderModelDropdown();
      expect(picker()?.classList.contains('hidden')).toBe(false);
    });
  });
});
