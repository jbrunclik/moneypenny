/**
 * Component tests for composer mode (questions rendered inside the pill).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  renderQuickActionComposer,
  readQuickActionComposerValues,
  focusQuickActionField,
} from '@/components/QuickActionComposer';
import type { QuickAction } from '@/types/api';

const action: QuickAction = {
  id: 'log',
  emoji: '📊',
  label: 'Log & review',
  body: 'Review.',
  fields: ['Hang time (s)', 'RPE'],
};

describe('QuickActionComposer', () => {
  let container: HTMLElement;
  beforeEach(() => {
    document.body.innerHTML = '<div id="quick-action-mode" class="qa-mode hidden"></div>';
    container = document.getElementById('quick-action-mode')!;
  });

  it('renders the header and one input per question', () => {
    renderQuickActionComposer(container, {
      action,
      onCancel: vi.fn(),
      onEscape: vi.fn(),
      onFieldEnter: vi.fn(),
    });
    expect(container.querySelector('.qa-mode-label')!.textContent).toBe('Log & review');
    const inputs = container.querySelectorAll<HTMLInputElement>('.qa-mode-field-input');
    expect(inputs.length).toBe(2);
    expect(container.querySelectorAll('.qa-mode-field-label')[1].textContent).toBe('RPE');
    expect(inputs[0].getAttribute('enterkeyhint')).toBe('next');
    expect(inputs[1].getAttribute('enterkeyhint')).toBe('send');
    expect(container.querySelector('img')).toBeNull();
  });

  it('reads values keyed by question label', () => {
    renderQuickActionComposer(container, {
      action,
      onCancel: vi.fn(),
      onEscape: vi.fn(),
      onFieldEnter: vi.fn(),
    });
    const inputs = container.querySelectorAll<HTMLInputElement>('.qa-mode-field-input');
    inputs[0].value = '54';
    expect(readQuickActionComposerValues(container)).toEqual({ 'Hang time (s)': '54', RPE: '' });
  });

  it('cancel button and Escape inside a field call back', () => {
    const onCancel = vi.fn();
    const onEscape = vi.fn();
    renderQuickActionComposer(container, { action, onCancel, onEscape, onFieldEnter: vi.fn() });
    (container.querySelector('.qa-mode-cancel') as HTMLButtonElement).click();
    expect(onCancel).toHaveBeenCalledTimes(1);
    container
      .querySelector<HTMLInputElement>('.qa-mode-field-input')!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it('Enter reports the field index and whether it is the last one', () => {
    const onFieldEnter = vi.fn();
    renderQuickActionComposer(container, { action, onCancel: vi.fn(), onEscape: vi.fn(), onFieldEnter });
    const inputs = container.querySelectorAll<HTMLInputElement>('.qa-mode-field-input');
    inputs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    inputs[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(onFieldEnter.mock.calls).toEqual([
      [0, false],
      [1, true],
    ]);
  });

  it('focusQuickActionField focuses by index and reports missing indexes', () => {
    renderQuickActionComposer(container, {
      action,
      onCancel: vi.fn(),
      onEscape: vi.fn(),
      onFieldEnter: vi.fn(),
    });
    expect(focusQuickActionField(container, 1)).toBe(true);
    expect(document.activeElement).toBe(
      container.querySelectorAll('.qa-mode-field-input')[1]
    );
    expect(focusQuickActionField(container, 5)).toBe(false);
  });
});
