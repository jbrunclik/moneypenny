import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/Toast', () => ({ toast: { info: vi.fn() } }));

import { useStore } from '@/state/store';
import { toast } from '@/components/Toast';
import { notifyModelFallback } from '@/core/model-fallback';

describe('notifyModelFallback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({
      models: [
        { id: 'gemini-fast', name: 'Gemini Fast', short_name: 'Fast' },
        { id: 'gemini-pro', name: 'Gemini Pro', short_name: 'Advanced' },
      ],
      currentConversation: { id: 'c1', title: 't', model: 'gemini-fast', created_at: '', updated_at: '' },
    } as never);
  });

  it('names both models by their short names', () => {
    notifyModelFallback('gemini-pro');

    expect(toast.info).toHaveBeenCalledWith('Fast is overloaded right now - Advanced answered instead.');
  });

  it('falls back to the raw id for an unknown model', () => {
    notifyModelFallback('gemini-other');

    expect(toast.info).toHaveBeenCalledWith('Fast is overloaded right now - gemini-other answered instead.');
  });
});
