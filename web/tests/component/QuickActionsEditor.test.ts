/**
 * Component tests for the quick-actions editor modal.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showQuickActionsEditor, closeQuickActionsEditor } from '@/components/QuickActionsEditor';
import type { QuickAction } from '@/types/api';

const a: QuickAction = {
  id: 'a',
  emoji: '📋',
  label: 'Plan today',
  body: 'Plan.',
  fields: ['Comments'],
};
const b: QuickAction = { id: 'b', emoji: '📊', label: 'Log', body: 'Log.', fields: [] };

const q = <T extends Element>(sel: string): T => document.querySelector<T>(sel)!;

describe('QuickActionsEditor', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => closeQuickActionsEditor());

  it('lists actions in order with edit/delete/move controls', () => {
    showQuickActionsEditor({ actions: [a, b], onSave: vi.fn() });
    const rows = document.querySelectorAll('.qa-editor-row');
    expect(rows.length).toBe(2);
    expect(rows[0].querySelector('.qa-editor-row-label')!.textContent).toBe('Plan today');
    expect(rows[0].querySelector('.qa-editor-move-up')).not.toBeNull();
    expect(rows[0].querySelector('.qa-editor-delete')).not.toBeNull();
  });

  it('move down reorders and Save sends the new order', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a, b], onSave });
    (document.querySelectorAll('.qa-editor-move-down')[0] as HTMLButtonElement).click();
    q<HTMLButtonElement>('.qa-editor-save').click();
    await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].map((x: QuickAction) => x.id)).toEqual(['b', 'a']);
  });

  it('delete removes the row', () => {
    showQuickActionsEditor({ actions: [a, b], onSave: vi.fn() });
    (document.querySelectorAll('.qa-editor-delete')[0] as HTMLButtonElement).click();
    expect(document.querySelectorAll('.qa-editor-row').length).toBe(1);
    expect(q('.qa-editor-row-label').textContent).toBe('Log');
  });

  it('Add opens the detail form; filling it and pressing Done appends a new action', () => {
    showQuickActionsEditor({ actions: [a], onSave: vi.fn() });
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
  });

  it('Done with an empty label or body shows an inline error and stays open', () => {
    showQuickActionsEditor({ actions: [], onSave: vi.fn() });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLButtonElement>('.qa-detail-done').click();
    expect(q('.qa-detail-error').textContent).toContain('Label and body are required');
    expect(document.querySelector('.qa-detail')).not.toBeNull();
  });

  it('initialDraft opens directly in the detail form prefilled', () => {
    showQuickActionsEditor({
      actions: [a],
      initialDraft: { body: 'Saved text' },
      onSave: vi.fn(),
    });
    expect(q<HTMLTextAreaElement>('.qa-detail-body').value).toBe('Saved text');
  });

  it('enforces the 12-action cap by disabling Add', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ ...a, id: `id${i}` }));
    showQuickActionsEditor({ actions: many, onSave: vi.fn() });
    expect(q<HTMLButtonElement>('.qa-editor-add').disabled).toBe(true);
  });

  it('Save failure keeps the editor open', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('boom'));
    showQuickActionsEditor({ actions: [a], onSave });
    q<HTMLButtonElement>('.qa-editor-save').click();
    await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
    await Promise.resolve();
    expect(document.querySelector('.qa-editor')).not.toBeNull();
  });
});
