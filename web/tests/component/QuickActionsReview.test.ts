/**
 * The Quick actions sheet's Review: suggestions for the program's quick actions
 * and instructions, each accepted or rejected on its own (program self-tuning).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { closeQuickActionsEditor, showQuickActionsEditor } from '@/components/QuickActionsEditor';
import { SuggestionRefreshed } from '@/api/setup-review';
import type { QuickAction, SetupSuggestion } from '@/types/api';

const next: QuickAction = { id: 'next', emoji: '⏭️', label: 'Next workout', body: 'Next?', fields: [] };
const planWeek: QuickAction = { id: 'plan-week', emoji: '📅', label: 'Plan week', body: 'Plan my week.', fields: [] };

const suggestion = (over: Partial<SetupSuggestion> = {}): SetupSuggestion => ({
  id: 'fp-1',
  change: { target: 'quick_action', op: 'add' },
  summary: 'Add a weekly plan',
  before: '(none)',
  after: 'Label: Plan week',
  changes: [
    { field: 'Label', before: '', after: 'Plan week' },
    { field: 'Message', before: 'Old text', after: 'Plan my week.' },
  ],
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

    // While it runs: the step it is on, the seconds so far, a moving bar and
    // placeholder cards shaped like suggestions
    expect(q('.qa-review-phase')?.textContent).toBe('Reading your quick actions and instructions…');
    expect(q('.qa-review-elapsed')?.textContent).toBe('0 s');
    expect(q('.qa-review-progress')?.getAttribute('role')).toBe('progressbar');
    expect(q('.qa-review-loading svg')).not.toBeNull();
    // No placeholder cards: they suggested how many results were coming
    expect(document.querySelectorAll('.qa-review-skeleton').length).toBe(0);

    resolve([suggestion()]);
    await flush();
    expect(q('.qa-review-loading')).toBeNull();
    const item = q('.qa-review-item');
    expect(item?.querySelector('.qa-review-summary')?.textContent).toBe('Add a weekly plan');
    // One row per changed field: its name, the old value (if any) and the new one
    const rows = item?.querySelectorAll('.qa-review-field') ?? [];
    expect(rows.length).toBe(2);
    expect(rows[0]?.querySelector('.qa-review-field-name')?.textContent).toBe('Label');
    expect(rows[0]?.querySelector('.qa-review-old')).toBeNull();
    expect(rows[0]?.querySelector('.qa-review-new')?.textContent).toBe('Plan week');
    expect(rows[1]?.querySelector('.qa-review-old')?.textContent).toBe('Old text');
    expect(rows[1]?.querySelector('.qa-review-new')?.textContent).toBe('Plan my week.');
    // Evidence: a "Based on" heading, each line the day (readable, machine date
    // kept) and the user's words as a quote
    const evidence = item?.querySelector('.qa-review-evidence');
    expect(evidence?.querySelector('.qa-review-evidence-title')?.textContent).toBe('Based on');
    expect(evidence?.querySelector('time')?.getAttribute('datetime')).toBe('2026-11-09');
    expect(evidence?.querySelector('q')?.textContent).toBe('plan my week');
    // The app's own buttons, as on proposal cards
    expect(item?.querySelector('.qa-review-accept')?.className).toContain('btn btn-primary btn-sm');
    expect(item?.querySelector('.qa-review-reject')?.className).toContain('btn btn-secondary btn-sm');
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
    // The outcome is a pill in the card's head; the evidence folds away
    expect(q('.qa-review-item-head .qa-review-item-status')?.textContent?.trim()).toBe('Applied');
    expect(q('.qa-review-item-status')?.getAttribute('data-tone')).toBe('applied');
    expect(q('.qa-review-item-status svg')).not.toBeNull();
    expect(q('.qa-review-evidence')).toBeNull();
    expect(q('.qa-review-accept')).toBeNull();

    // Back to the list: it shows the applied change
    q<HTMLButtonElement>('.qa-review-back')?.click();
    const labels = [...document.querySelectorAll('.qa-editor-row-label')].map((el) => el.textContent);
    expect(labels).toEqual(['Next workout', 'Plan week']);
  });

  it('titles the list with its count and says when every suggestion is answered', async () => {
    open({ load: () => Promise.resolve([suggestion(), suggestion({ id: 'fp-2', summary: 'Second' })]) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    expect(q('.qa-review-title')?.textContent).toBe('2 suggestions');

    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();
    expect(q('.qa-review-done')).toBeNull(); // one still open
    document.querySelectorAll<HTMLButtonElement>('.qa-review-reject')[0]?.click();
    await flush();
    // The app's empty-state look: a green tick, "All done" and what came of it
    expect(q('.qa-review-done .empty-state__title')?.textContent).toBe('All done');
    expect(q('.qa-review-done .empty-state__hint')?.textContent).toBe('1 applied, 1 rejected.');
  });

  it('Reject records it and marks it rejected', async () => {
    const { handlers } = open({});
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-reject')?.click();
    await flush();

    expect(handlers.reject).toHaveBeenCalledWith(suggestion());
    expect(q('.qa-review-item')?.getAttribute('data-state')).toBe('rejected');
    expect(q('.qa-review-item-status')?.textContent?.trim()).toBe('Rejected');
    expect(q('.qa-review-item-status')?.getAttribute('data-tone')).toBe('rejected');
    // A rejected change is no longer worth reading: just its summary and the pill
    expect(q('.qa-review-change')).toBeNull();
    expect(q('.qa-review-evidence')).toBeNull();
  });

  it('says what it is doing while Accept waits', async () => {
    let finish: (a: QuickAction[]) => void = () => undefined;
    open({ apply: () => new Promise((r) => (finish = r)) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    expect(q('.qa-review-accept')?.textContent).toBe('Applying…');
    expect(q<HTMLButtonElement>('.qa-review-reject')?.disabled).toBe(true);
    finish([next]);
    await flush();
    expect(q('.qa-review-item')?.getAttribute('data-state')).toBe('applied');
  });

  it('a failed accept says so and keeps the buttons', async () => {
    open({ apply: () => Promise.reject(new Error('That quick action no longer exists')) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();

    expect(q('.qa-review-item-status')?.textContent?.trim()).toContain('no longer exists');
    expect(q('.qa-review-item-status')?.getAttribute('data-tone')).toBe('error');
    expect(q('.qa-review-accept')?.textContent).toBe('Accept');
  });

  it('steps through what it is doing and counts the seconds while it waits', async () => {
    vi.useFakeTimers();
    try {
      open({ load: () => new Promise(() => undefined) });
      q<HTMLButtonElement>('.qa-editor-review')?.click();

      await vi.advanceTimersByTimeAsync(3000);
      expect(q('.qa-review-phase')?.textContent).toBe('Going through your recent chats…');
      expect(q('.qa-review-elapsed')?.textContent).toBe('3 s');

      await vi.advanceTimersByTimeAsync(20000);
      expect(q('.qa-review-phase')?.textContent).toBe('Checking each suggestion…');
      expect(q('.qa-review-elapsed')?.textContent).toBe('23 s');
    } finally {
      vi.useRealTimers();
    }
  });

  it('a collision on Accept shows the refreshed change in place, ready to accept again', async () => {
    const refreshed = suggestion({
      summary: 'Add a weekly plan',
      changes: [{ field: 'Message', before: 'Edited meanwhile', after: 'Plan my week.' }],
    });
    const apply = vi
      .fn<(s: SetupSuggestion) => Promise<QuickAction[]>>()
      .mockRejectedValueOnce(new SuggestionRefreshed(refreshed))
      .mockResolvedValueOnce([next, planWeek]);
    open({ apply });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();

    expect(q('.qa-review-item-status')?.textContent?.trim()).toBe('This changed since the review - here is the updated change.');
    expect(q('.qa-review-item-status')?.getAttribute('data-tone')).toBe('info');
    expect(q('.qa-review-old')?.textContent).toBe('Edited meanwhile');
    q<HTMLButtonElement>('.qa-review-accept')?.click();
    await flush();
    expect(apply).toHaveBeenLastCalledWith(refreshed);
    expect(q('.qa-review-item')?.getAttribute('data-state')).toBe('applied');
  });

  it('says when there is nothing to change', async () => {
    open({ load: () => Promise.resolve([]) });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    expect(q('.qa-review-empty .empty-state__title')?.textContent).toBe('Nothing to change');
    expect(q('.qa-review-empty .empty-state__hint')?.textContent).toBe(
      'Your quick actions and instructions match how you use them.'
    );
  });

  it('a failed review offers a retry', async () => {
    const load = vi
      .fn<() => Promise<SetupSuggestion[]>>()
      .mockRejectedValueOnce(new Error('It took too long to answer.'))
      .mockResolvedValueOnce([suggestion()]);
    open({ load });
    q<HTMLButtonElement>('.qa-editor-review')?.click();
    await flush();
    // One notice: what failed, why, that nothing changed, and Try again
    expect(q('.qa-review-error-title')?.textContent).toBe('The review failed.');
    expect(q('.qa-review-error svg')).not.toBeNull();
    // Why, and that nothing changed
    expect(q('.qa-review-error-detail')?.textContent).toBe(
      'It took too long to answer. Nothing was changed.'
    );

    q<HTMLButtonElement>('.qa-review-retry')?.click();
    await flush();
    expect(q('.qa-review-item')).not.toBeNull();
  });
});
