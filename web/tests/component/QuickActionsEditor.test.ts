/**
 * Component tests for the quick-actions editor modal (autosave).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showQuickActionsEditor, closeQuickActionsEditor } from '@/components/QuickActionsEditor';
import type { QuickAction } from '@/types/api';

function at<T>(items: ArrayLike<T>, i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item at index ${i}`);
  return item;
}

const a: QuickAction = {
  id: 'a',
  emoji: '📋',
  label: 'Plan today',
  body: 'Plan.',
  fields: ['Comments'],
};
const b: QuickAction = { id: 'b', emoji: '📊', label: 'Log', body: 'Log.', fields: [] };

const q = <T extends Element>(sel: string): T => document.querySelector<T>(sel)!;
const ids = (list: QuickAction[]): string[] => list.map((x) => x.id);

describe('QuickActionsEditor', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => closeQuickActionsEditor());

  it('lists actions in order with edit/delete/move controls and no Save footer', () => {
    showQuickActionsEditor({ actions: [a, b], onChange: vi.fn() });
    const rows = document.querySelectorAll('.qa-editor-row');
    expect(rows.length).toBe(2);
    expect(rows[0]?.querySelector('.qa-editor-row-label')!.textContent).toBe('Plan today');
    expect(at(rows, 0).querySelector('.qa-editor-move-up')).not.toBeNull();
    expect(at(rows, 0).querySelector('.qa-editor-delete')).not.toBeNull();
    expect(document.querySelector('.qa-editor-save')).toBeNull();
  });

  it('move down reorders and autosaves the new order', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a, b], onChange });
    (document.querySelectorAll('.qa-editor-move-down')[0] as HTMLButtonElement).click();
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(ids(onChange.mock.calls[0]?.[0])).toEqual(['b', 'a']);
  });

  it('delete removes the row and autosaves', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a, b], onChange });
    (document.querySelectorAll('.qa-editor-delete')[0] as HTMLButtonElement).click();
    expect(document.querySelectorAll('.qa-editor-row').length).toBe(1);
    expect(q('.qa-editor-row-label').textContent).toBe('Log');
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(ids(onChange.mock.calls[0]?.[0])).toEqual(['b']);
  });

  it('Add + Done appends a new action and autosaves it', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a], onChange });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLInputElement>('.qa-detail-label').value = 'Week overview';
    q<HTMLTextAreaElement>('.qa-detail-body').value = 'Summarize the week.';
    q<HTMLInputElement>('.qa-detail-field-input').value = 'Notes';
    q<HTMLButtonElement>('.qa-detail-field-add').click();
    q<HTMLButtonElement>('.qa-detail-done').click();
    const labels = [...document.querySelectorAll('.qa-editor-row-label')].map(
      (e) => e.textContent
    );
    expect(labels).toEqual(['Plan today', 'Week overview']);
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const saved = onChange.mock.calls[0]?.[0] as QuickAction[];
    expect(saved.length).toBe(2);
    expect(saved[1]?.label).toBe('Week overview');
    expect(saved[1]?.fields).toEqual(['Notes']);
  });

  it('closing over a valid, unfinished detail form commits it (regression: lost action)', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [], onChange });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLInputElement>('.qa-detail-label').value = 'Evaluate';
    q<HTMLTextAreaElement>('.qa-detail-body').value = 'Evaluate my session.';
    q<HTMLButtonElement>('.qa-editor-close').click();
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const saved = onChange.mock.calls[0]?.[0] as QuickAction[];
    expect(saved.map((x) => x.label)).toEqual(['Evaluate']);
    expect(document.querySelector('.qa-editor')).toBeNull();
  });

  it('closing over an invalid detail form discards it without saving', () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a], onChange });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLInputElement>('.qa-detail-label').value = 'No body';
    q<HTMLButtonElement>('.qa-editor-close').click();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('renders questions as rows with a Remove button and updates the preview', () => {
    showQuickActionsEditor({ actions: [a], onChange: vi.fn() });
    (document.querySelectorAll('.qa-editor-edit')[0] as HTMLButtonElement).click();
    expect(q('.qa-detail-field-row .qa-detail-field-name').textContent).toBe('Comments');
    expect(q('.qa-detail-preview').textContent).toBe('Plan.\n\nComments: …');
    q<HTMLInputElement>('.qa-detail-field-input').value = 'RPE';
    q<HTMLButtonElement>('.qa-detail-field-add').click();
    expect(document.querySelectorAll('.qa-detail-field-row').length).toBe(2);
    expect(q('.qa-detail-preview').textContent).toBe('Plan.\n\nComments: …\nRPE: …');
    (document.querySelectorAll('.qa-detail-field-remove')[0] as HTMLButtonElement).click();
    expect(document.querySelectorAll('.qa-detail-field-row').length).toBe(1);
    expect(q('.qa-detail-preview').textContent).toBe('Plan.\n\nRPE: …');
  });

  it('questions can be reordered with up/down and the order is saved', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    const two: QuickAction = { ...a, fields: ['Hang time (s)', 'Comments'] };
    showQuickActionsEditor({ actions: [two], onChange });
    (document.querySelectorAll('.qa-editor-edit')[0] as HTMLButtonElement).click();
    (document.querySelectorAll('.qa-detail-field-down')[0] as HTMLButtonElement).click();
    const names = [...document.querySelectorAll('.qa-detail-field-name')].map(
      (e) => e.textContent
    );
    expect(names).toEqual(['Comments', 'Hang time (s)']);
    expect(q('.qa-detail-preview').textContent).toBe('Plan.\n\nComments: …\nHang time (s): …');
    q<HTMLButtonElement>('.qa-detail-done').click();
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect((onChange.mock.calls[0]?.[0] as QuickAction[])[0]?.fields).toEqual([
      'Comments',
      'Hang time (s)',
    ]);
  });

  it('accepts any typed emoji for the icon, keeping only the first character', () => {
    showQuickActionsEditor({ actions: [], onChange: vi.fn().mockResolvedValue(undefined) });
    q<HTMLButtonElement>('.qa-editor-add').click();
    const emojiInput = q<HTMLInputElement>('.qa-detail-emoji-input');
    emojiInput.value = '🧗‍♂️🔥';
    emojiInput.dispatchEvent(new Event('input', { bubbles: true }));
    q<HTMLInputElement>('.qa-detail-label').value = 'Climb';
    q<HTMLTextAreaElement>('.qa-detail-body').value = 'Log the climb.';
    q<HTMLButtonElement>('.qa-detail-done').click();
    expect(q('.qa-editor-row-emoji').textContent).toBe('🧗‍♂️');
  });

  it('Done with an empty label or body shows an inline error and stays open', () => {
    showQuickActionsEditor({ actions: [], onChange: vi.fn() });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLButtonElement>('.qa-detail-done').click();
    expect(q('.qa-detail-error').textContent).toContain('Label and body are required');
    expect(document.querySelector('.qa-detail')).not.toBeNull();
  });

  it('initialDraft opens directly in the detail form prefilled', () => {
    showQuickActionsEditor({
      actions: [a],
      initialDraft: { body: 'Saved text' },
      onChange: vi.fn(),
    });
    expect(q<HTMLTextAreaElement>('.qa-detail-body').value).toBe('Saved text');
  });

  it('enforces the 12-action cap by disabling Add', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ ...a, id: `id${i}` }));
    showQuickActionsEditor({ actions: many, onChange: vi.fn() });
    expect(q<HTMLButtonElement>('.qa-editor-add').disabled).toBe(true);
  });

  it('a failed autosave shows an error and keeps the editor open with the draft', async () => {
    const onChange = vi.fn().mockRejectedValue(new Error('boom'));
    showQuickActionsEditor({ actions: [a, b], onChange });
    (document.querySelectorAll('.qa-editor-delete')[0] as HTMLButtonElement).click();
    await vi.waitFor(() => expect(onChange).toHaveBeenCalled());
    await Promise.resolve();
    expect(document.querySelector('.qa-editor')).not.toBeNull();
    expect(document.querySelectorAll('.qa-editor-row').length).toBe(1);
  });
});

describe('QuickActionsEditor detail form', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => closeQuickActionsEditor());

  it('Edit + Done replaces the action in place, keeping its id', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a, b], onChange });
    (document.querySelectorAll('.qa-editor-edit')[1] as HTMLButtonElement).click();
    expect(q<HTMLInputElement>('.qa-detail-label').value).toBe('Log');
    q<HTMLInputElement>('.qa-detail-label').value = 'Log workout';
    q<HTMLButtonElement>('.qa-detail-done').click();

    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const saved = onChange.mock.calls[0]?.[0] as QuickAction[];
    expect(saved.map((x) => [x.id, x.label])).toEqual([['a', 'Plan today'], ['b', 'Log workout']]);
  });

  it('Cancel returns to the list without saving', () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a], onChange });
    (document.querySelector('.qa-editor-edit') as HTMLButtonElement).click();
    q<HTMLInputElement>('.qa-detail-label').value = 'Changed';
    q<HTMLButtonElement>('.qa-detail-back').click();

    expect(q('.qa-editor-row-label').textContent).toBe('Plan today');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('picks an emoji from the suggestions', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [], onChange });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLInputElement>('.qa-detail-emoji-input').focus();
    expect(q('.qa-detail-emoji-popover').classList.contains('open')).toBe(true);
    const option = at(document.querySelectorAll<HTMLButtonElement>('.qa-detail-emoji-option'), 2);
    const picked = option.dataset.emoji;
    option.click();
    expect(q<HTMLInputElement>('.qa-detail-emoji-input').value).toBe(picked);
    expect(q('.qa-detail-emoji-popover').classList.contains('open')).toBe(false);

    q<HTMLInputElement>('.qa-detail-label').value = 'Stretch';
    q<HTMLTextAreaElement>('.qa-detail-body').value = 'Stretch with me.';
    q<HTMLButtonElement>('.qa-detail-done').click();
    await vi.waitFor(() => expect(onChange).toHaveBeenCalled());
    expect((onChange.mock.calls[0]?.[0] as QuickAction[])[0]?.emoji).toBe(picked);
  });

  it('keeps a typed but unadded question on Done', async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [], onChange });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLInputElement>('.qa-detail-label').value = 'Check in';
    q<HTMLTextAreaElement>('.qa-detail-body').value = 'How was it?';
    q<HTMLInputElement>('.qa-detail-field-input').value = 'Mood';
    q<HTMLButtonElement>('.qa-detail-done').click();

    await vi.waitFor(() => expect(onChange).toHaveBeenCalled());
    expect((onChange.mock.calls[0]?.[0] as QuickAction[])[0]?.fields).toEqual(['Mood']);
  });

  it('adds a question on Enter and stops at the question cap', () => {
    showQuickActionsEditor({ actions: [], onChange: vi.fn() });
    q<HTMLButtonElement>('.qa-editor-add').click();
    const input = q<HTMLInputElement>('.qa-detail-field-input');
    for (let i = 0; i < 6; i++) {
      input.value = `Q${i}`;
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    }
    expect(document.querySelectorAll('.qa-detail-field-row')).toHaveLength(6);
    expect(input.disabled).toBe(true);
    expect(q<HTMLButtonElement>('.qa-detail-field-add').disabled).toBe(true);
    expect(input.placeholder).toBe('Max 6');
    expect(q('.qa-detail-preview').textContent).toContain('Q5: …');
  });

  it('closes on Escape and on a backdrop click', () => {
    showQuickActionsEditor({ actions: [a], onChange: vi.fn() });
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.querySelector('.qa-editor')).toBeNull();

    showQuickActionsEditor({ actions: [a], onChange: vi.fn() });
    q<HTMLElement>('.qa-editor-overlay').click();
    expect(document.querySelector('.qa-editor')).toBeNull();
  });
});
