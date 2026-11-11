/**
 * Settings → AI Instructions: the Review button suggests changes to the
 * custom instructions (and the memories on their border); an accepted change
 * lands in the textarea, the counter and the store (instructions self-tuning).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { SetupSuggestion } from '@/types/api';

const api = vi.hoisted(() => ({
  review: vi.fn<() => Promise<SetupSuggestion[]>>(),
  apply: vi.fn<(s: SetupSuggestion) => Promise<string>>(),
  reject: vi.fn<(s: SetupSuggestion) => Promise<void>>(),
  update: vi.fn<(data: unknown) => Promise<void>>(),
}));

vi.mock('@/api/settings', () => ({
  settings: { update: api.update },
  instructionsReview: { review: api.review, apply: api.apply, reject: api.reject },
}));

import { bindInstructionsField, renderInstructionsSection } from '@/components/settings/instructions';
import { useStore } from '@/state/store';
import { CUSTOM_INSTRUCTIONS_MAX_CHARS } from '@/config';

const RULE = 'Never use bullet points.';
const suggestion: SetupSuggestion = {
  id: 'fp-1',
  change: { instructions: { op: 'append', new: RULE } },
  summary: 'No bullet points',
  before: '(none)',
  after: `Instructions: ${RULE}`,
  changes: [{ field: 'Instructions', before: '', after: RULE }],
  evidence: ['2026-11-11: stop using bullet points please', 'Memory: Prefers answers without bullets'],
};

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));
const q = <T extends Element>(sel: string): T | null => document.querySelector<T>(sel);

function mount(saved = 'Answer in Czech.'): void {
  useStore.getState().setUserSettings({
    ...(useStore.getState().userSettings ?? {}),
    custom_instructions: saved,
  } as never);
  document.body.replaceChildren(renderInstructionsSection());
  bindInstructionsField();
}

describe('instructions Review in Settings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.review.mockResolvedValue([suggestion]);
    api.apply.mockResolvedValue(`Answer in Czech.\n\n${RULE}`);
    api.reject.mockResolvedValue(undefined);
    api.update.mockResolvedValue(undefined);
  });

  it('shows the suggestions with their field rows and evidence kinds', async () => {
    mount();
    q<HTMLButtonElement>('.settings-instructions-review')?.click();
    await flush();
    await flush();

    expect(q('.qa-review-summary')?.textContent).toBe('No bullet points');
    expect(q('.qa-review-new')?.textContent).toBe(RULE);
    // A clean-up item is labelled with what it quotes
    expect(q('.qa-review-evidence-kind')?.textContent).toBe('Memory');
  });

  it('an accepted change lands in the textarea, the counter and the store', async () => {
    mount();
    q<HTMLButtonElement>('.settings-instructions-review')?.click();
    await flush();
    await flush();
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();

    const text = `Answer in Czech.\n\n${RULE}`;
    expect(q<HTMLTextAreaElement>('#custom-instructions')?.value).toBe(text);
    expect(q('.settings-char-count')?.textContent).toBe(`${text.length}/${CUSTOM_INSTRUCTIONS_MAX_CHARS}`);
    expect(useStore.getState().userSettings?.custom_instructions).toBe(text);
    expect(q('.qa-review-item')?.getAttribute('data-state')).toBe('applied');
  });

  it('saves unsaved typing before it reviews', async () => {
    mount();
    const textarea = q<HTMLTextAreaElement>('#custom-instructions');
    if (textarea) textarea.value = 'Answer in Czech. Be brief.';
    q<HTMLButtonElement>('.settings-instructions-review')?.click();
    await flush();
    await flush();

    expect(api.update).toHaveBeenCalledWith({ custom_instructions: 'Answer in Czech. Be brief.' });
    expect(api.update.mock.invocationCallOrder[0]).toBeLessThan(api.review.mock.invocationCallOrder[0] ?? 0);
  });

  it('Accept waits for a save the blur started (typing after the Review opened)', async () => {
    // Final review I3: an apply that beat the PATCH was overwritten by it
    let saved: () => void = () => undefined;
    api.update.mockImplementation(() => new Promise<void>((r) => (saved = r)));
    mount();
    q<HTMLButtonElement>('.settings-instructions-review')?.click();
    await flush();
    saved();
    await flush();
    await flush();
    const textarea = q<HTMLTextAreaElement>('#custom-instructions');
    if (textarea) {
      textarea.value = 'Answer in Czech. Typed later.';
      textarea.dispatchEvent(new Event('blur'));
    }
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();
    expect(api.apply).not.toHaveBeenCalled(); // the save is still running
    saved();
    await flush();
    await flush();
    expect(api.apply).toHaveBeenCalledTimes(1);
  });

  it('the Review button is the small secondary button used across the app', () => {
    mount();
    expect(q('.settings-instructions-review')?.className).toContain('btn btn-secondary btn-sm');
  });

  it('closes with an icon button in the header, not a Done that reads as finished', async () => {
    mount();
    q<HTMLButtonElement>('.settings-instructions-review')?.click();
    await flush();
    await flush();

    const close = q<HTMLButtonElement>('.qa-review-header .qa-review-close');
    expect(close?.getAttribute('aria-label')).toBe('Close suggestions');
    expect(close?.textContent?.trim()).toBe('');
    expect(q('.qa-review-header')?.textContent).not.toContain('Done');
  });

  it('says when there is nothing to change, and closing ends the Review', async () => {
    api.review.mockResolvedValue([]);
    mount();
    q<HTMLButtonElement>('.settings-instructions-review')?.click();
    await flush();
    await flush();

    expect(q('.qa-review-empty .empty-state__title')?.textContent).toBe('Nothing to change');
    q<HTMLButtonElement>('.qa-review-back')?.click();
    expect(q('.qa-review-list')).toBeNull();
    expect(q<HTMLButtonElement>('.settings-instructions-review')?.hidden).toBe(false);
  });
});
