/**
 * Component tests for the quick-actions chip bar.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderQuickActionsBar, setQuickActionsBarDisabled } from '@/components/QuickActionsBar';
import type { QuickAction } from '@/types/api';

const actions: QuickAction[] = [
  { id: 'a', emoji: '📋', label: 'Plan today', body: 'Plan.', fields: [] },
  { id: 'b', emoji: '📊', label: 'Log & review', body: 'Log.', fields: ['Comments'] },
];

describe('QuickActionsBar', () => {
  let container: HTMLElement;
  beforeEach(() => {
    document.body.innerHTML = '<div id="quick-actions-bar" class="quick-actions-bar hidden"></div>';
    container = document.getElementById('quick-actions-bar')!;
  });

  it('renders one chip per action with emoji, label and data-action-id', () => {
    renderQuickActionsBar(container, actions, vi.fn());
    const chips = container.querySelectorAll<HTMLButtonElement>('.quick-action-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].dataset.actionId).toBe('a');
    expect(chips[0].querySelector('.quick-action-chip-emoji')!.textContent).toBe('📋');
    expect(chips[0].querySelector('.quick-action-chip-label')!.textContent).toBe('Plan today');
  });

  it('escapes label text (no HTML injection)', () => {
    renderQuickActionsBar(
      container,
      [{ ...actions[0], label: '<img src=x onerror=alert(1)>' }],
      vi.fn()
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('.quick-action-chip-label')!.textContent).toContain('<img');
  });

  it('calls onTap with the action and chip element (event delegation)', () => {
    const onTap = vi.fn();
    renderQuickActionsBar(container, actions, onTap);
    const chip = container.querySelectorAll<HTMLButtonElement>('.quick-action-chip')[1];
    chip
      .querySelector('.quick-action-chip-label')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onTap).toHaveBeenCalledWith(actions[1], chip);
  });

  it('re-render replaces chips instead of appending', () => {
    renderQuickActionsBar(container, actions, vi.fn());
    renderQuickActionsBar(container, actions.slice(0, 1), vi.fn());
    expect(container.querySelectorAll('.quick-action-chip').length).toBe(1);
  });

  it('disabled state disables every chip', () => {
    renderQuickActionsBar(container, actions, vi.fn());
    setQuickActionsBarDisabled(container, true);
    const chips = container.querySelectorAll<HTMLButtonElement>('.quick-action-chip');
    expect([...chips].every((c) => c.disabled)).toBe(true);
    setQuickActionsBarDisabled(container, false);
    expect([...chips].every((c) => !c.disabled)).toBe(true);
  });
});
