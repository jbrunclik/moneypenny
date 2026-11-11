/**
 * The Quick actions sheet's Review: suggestions for the program's quick actions
 * and instructions, each accepted or rejected on its own (program self-tuning).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { closeQuickActionsEditor, showQuickActionsEditor } from '@/components/QuickActionsEditor';
import type { QuickAction, SetupSuggestion } from '@/types/api';

const next: QuickAction = { id: 'next', emoji: '⏭️', label: 'Next workout', body: 'Next?', fields: [] };
const planWeek: QuickAction = { id: 'plan-week', emoji: '📅', label: 'Plan week', body: 'Plan my week.', fields: [] };

const suggestion = (over: Partial<SetupSuggestion> = {}): SetupSuggestion => ({
  id: 'fp-1',
  change: { target: 'quick_action', op: 'add' },
  summary: 'Add a weekly plan',
  before: '(none)',
  after: "📅 Plan week: 'Plan my week.'",
  evidence: ['2026-11-09: plan my week'],
  ...over,
});

const q = <T extends Element>(sel: string): T | null => document.querySelector<T>(sel);
const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

function open(review: {
  load?: () => Promise<SetupSuggestion[]>;
  apply?: (s: SetupSuggestion) => Promise<QuickAction[]>;
  reject?: (s: SetupSuggestion) => Promise<void>;
}) {
  const handlers = {
    load: review.load ?? vi.fn(() => Promise.resolve([suggestion()])),
    apply: review.apply ?? vi.fn(() => Promise.resolve([next, planWeek])),
    reject: review.reject ?? vi.fn(() => Promise.resolve()),
  };
  const onApplied = vi.fn();
  showQuickActionsEditor({ actions: [next], onChange: vi.fn(), review: { ...handlers, onApplied } });
  return { handlers, onApplied };
}

describe('Quick actions Review', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => closeQuickActionsEditor());

  it('offers Review next to Add only when the sheet has review handlers', () => {
    showQuickActionsEditor({ actions: [next], onChange: vi.fn() });
    expect(q('.qa-editor-review')).toBeNull();
    closeQuickActionsEditor();
    open({});
    expect(q('.qa-editor-review')?.textContent).toContain('Review');
  });

  it('shows a loading line, then each suggestion with before, after and evidence', async () => {
    let resolve: (s: SetupSuggestion[]) => void = () => undefined;
    open({ load: () => new Promise((r) => (resolve = r)) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    expect(q('.qa-review-status')?.textContent).toBe('Reviewing your quick actions and recent chats…');

    resolve([suggestion()]);
    await flush();
    const item = q('.qa-review-item');
    expect(item?.querySelector('.qa-review-summary')?.textContent).toBe('Add a weekly plan');
    expect(item?.querySelector('.qa-review-before')?.textContent).toContain('(none)');
    expect(item?.querySelector('.qa-review-after')?.textContent).toContain('Plan week');
    expect(item?.querySelector('.qa-review-evidence')?.textContent).toContain('2026-11-09: plan my week');
    expect(item?.querySelector('.qa-review-accept')).not.toBeNull();
    expect(item?.querySelector('.qa-review-reject')).not.toBeNull();
  });

  it('Accept applies the suggestion, marks it applied and hands back the new actions', async () => {
    const { handlers, onApplied } = open({});
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();

    expect(handlers.apply).toHaveBeenCalledWith(suggestion());
    expect(onApplied).toHaveBeenCalledWith([next, planWeek]);
    expect(q('.qa-review-item')?.getAttribute('data-state')).toBe('applied');
    expect(q('.qa-review-item-status')?.textContent).toBe('Applied');
    expect(q('.qa-review-accept')).toBeNull();

    // Back to the list: it shows the applied change
    q<HTMLButtonElement>('.qa-review-back')?.click();
    const labels = [...document.querySelectorAll('.qa-editor-row-label')].map((el) => el.textContent);
    expect(labels).toEqual(['Next workout', 'Plan week']);
  });

  it('Reject records it and marks it rejected', async () => {
    const { handlers } = open({});
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-reject')?.click();
    await flush();

    expect(handlers.reject).toHaveBeenCalledWith(suggestion());
    expect(q('.qa-review-item')?.getAttribute('data-state')).toBe('rejected');
    expect(q('.qa-review-item-status')?.textContent).toBe('Rejected');
  });

  it('a failed accept says so and keeps the buttons', async () => {
    open({ apply: () => Promise.reject(new Error('That quick action no longer exists')) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();

    expect(q('.qa-review-item-status')?.textContent).toContain('no longer exists');
    expect(q('.qa-review-accept')).not.toBeNull();
  });

  it('says when there is nothing to change', async () => {
    open({ load: () => Promise.resolve([]) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    expect(q('.qa-review-status')?.textContent).toBe(
      'Nothing to change - your quick actions and instructions match how you use them.'
    );
  });

  it('a failed review offers a retry', async () => {
    const load = vi
      .fn<() => Promise<SetupSuggestion[]>>()
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce([suggestion()]);
    open({ load });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    expect(q('.qa-review-status')?.textContent).toBe('The review failed.');

    q<HTMLButtonElement>('.qa-review-retry')?.click();
    await flush();
    expect(q('.qa-review-item')).not.toBeNull();
  });
});
