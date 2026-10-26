/**
 * Which action buttons a message gets, by role and content.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { createMessageActions } from '@/components/messages/actions';
import type { GeneratedImage, Source } from '@/types/api';

const buttons = (actions: HTMLElement): string[] =>
  [...actions.querySelectorAll('button')].map((b) => b.className);

describe('createMessageActions', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('gives an assistant reply rerun, cost and delete, plus sources and image info when it has them', () => {
    vi.stubGlobal('speechSynthesis', {});
    const sources = [{ url: 'https://a.cz', title: 'A' }] as unknown as Source[];
    const images = [{ prompt: 'a cat' }] as unknown as GeneratedImage[];

    const actions = createMessageActions('m1', '2026-09-04T10:00:00Z', sources, images, 'assistant');

    expect(buttons(actions)).toEqual([
      'message-copy-btn',
      'message-actions-overflow',
      'message-regenerate-btn',
      'message-continue-btn',
      'message-sources-btn',
      'message-imagegen-btn',
      'message-cost-btn',
      'message-speak-btn',
      'message-delete-btn',
    ]);
    expect(actions.querySelector('.message-sources-btn')?.getAttribute('title')).toBe('View sources (1)');
    expect(actions.querySelector('.message-time')).not.toBeNull();
  });

  it('gives a user message edit and save-as-quick-action, no assistant-only buttons', () => {
    vi.stubGlobal('speechSynthesis', {});
    const actions = createMessageActions('m2', undefined, [], [], 'user');

    expect(buttons(actions)).toEqual([
      'message-copy-btn',
      'message-actions-overflow',
      'message-edit-btn',
      'message-save-quick-action-btn',
      'message-delete-btn',
    ]);
    expect(actions.querySelector('.message-time')).toBeNull();
  });

  it('omits read-aloud where speech synthesis is unavailable', () => {
    vi.stubGlobal('speechSynthesis', undefined);
    const actions = createMessageActions('m3', undefined, undefined, undefined, 'assistant');

    expect(actions.querySelector('.message-speak-btn')).toBeNull();
    expect(actions.querySelector('.message-cost-btn')).not.toBeNull();
  });
});
