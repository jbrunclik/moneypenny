/**
 * Component tests for the quick-action field form.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showQuickActionForm, closeQuickActionForm } from '@/components/QuickActionForm';
import type { QuickAction } from '@/types/api';

const action: QuickAction = {
  id: 'log',
  emoji: '📊',
  label: 'Log & review',
  body: 'Assess.',
  fields: ['Hang time (s)', 'Comments'],
};

describe('QuickActionForm', () => {
  let anchor: HTMLElement;
  beforeEach(() => {
    document.body.innerHTML = '<button id="anchor">chip</button>';
    anchor = document.getElementById('anchor')!;
  });
  afterEach(() => closeQuickActionForm());

  it('renders one textarea per field with the label, first field focused', () => {
    showQuickActionForm(action, anchor, vi.fn());
    const form = document.querySelector('.quick-action-form')!;
    const areas = form.querySelectorAll<HTMLTextAreaElement>('textarea');
    expect(areas.length).toBe(2);
    expect(form.querySelectorAll('label')[0].textContent).toBe('Hang time (s)');
    expect(document.activeElement).toBe(areas[0]);
    expect(form.querySelector('.quick-action-form-title')!.textContent).toContain('Log & review');
  });

  it('Send calls onSend with values keyed by field label and closes', () => {
    const onSend = vi.fn();
    showQuickActionForm(action, anchor, onSend);
    const areas = document.querySelectorAll<HTMLTextAreaElement>('.quick-action-form textarea');
    areas[0].value = '54';
    areas[1].value = 'felt ok';
    (document.querySelector('.quick-action-form-send') as HTMLButtonElement).click();
    expect(onSend).toHaveBeenCalledWith({ 'Hang time (s)': '54', Comments: 'felt ok' });
    expect(document.querySelector('.quick-action-form')).toBeNull();
  });

  it('Cancel and Escape close without sending', () => {
    const onSend = vi.fn();
    showQuickActionForm(action, anchor, onSend);
    (document.querySelector('.quick-action-form-cancel') as HTMLButtonElement).click();
    expect(document.querySelector('.quick-action-form')).toBeNull();
    showQuickActionForm(action, anchor, onSend);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.querySelector('.quick-action-form')).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('Cmd/Ctrl+Enter inside a field sends', () => {
    const onSend = vi.fn();
    showQuickActionForm(action, anchor, onSend);
    const area = document.querySelector<HTMLTextAreaElement>('.quick-action-form textarea')!;
    area.value = '60';
    area.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true })
    );
    expect(onSend).toHaveBeenCalledWith({ 'Hang time (s)': '60', Comments: '' });
  });

  it('opening a second form replaces the first', () => {
    showQuickActionForm(action, anchor, vi.fn());
    showQuickActionForm(action, anchor, vi.fn());
    expect(document.querySelectorAll('.quick-action-form').length).toBe(1);
  });
});
