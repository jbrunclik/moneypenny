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
});
