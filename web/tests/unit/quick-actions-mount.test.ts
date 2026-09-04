/**
 * mount/unmount of the quick-actions bar and the body marker class.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  mountQuickActionsBar,
  unmountQuickActionsBar,
  getQuickActionsContext,
} from '@/core/quick-actions';

describe('quick actions mount', () => {
  beforeEach(() => {
    document.body.className = '';
    document.body.innerHTML = `
      <div class="input-area"><div class="input-wrapper">
        <div id="quick-actions-bar" class="quick-actions-bar hidden"></div>
        <div id="input-container"><textarea id="message-input"></textarea></div>
      </div></div>`;
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true });
  });

  it('mount renders chips, shows the bar and marks body; unmount hides and unmarks', () => {
    mountQuickActionsBar({
      namespace: 'sports',
      programId: 'pushups',
      actions: [{ id: 'a', emoji: '📋', label: 'Plan', body: 'Plan.', fields: [] }],
      save: vi.fn(),
    });
    const bar = document.getElementById('quick-actions-bar')!;
    expect(bar.classList.contains('hidden')).toBe(false);
    expect(bar.querySelectorAll('.quick-action-chip').length).toBe(1);
    expect(document.body.classList.contains('has-quick-actions')).toBe(true);
    expect(getQuickActionsContext()?.programId).toBe('pushups');

    unmountQuickActionsBar();
    expect(bar.classList.contains('hidden')).toBe(true);
    expect(document.body.classList.contains('has-quick-actions')).toBe(false);
    expect(getQuickActionsContext()).toBeNull();
  });

  it('mount with zero actions keeps the bar hidden', () => {
    mountQuickActionsBar({ namespace: 'language', programId: 'es', actions: [], save: vi.fn() });
    expect(document.getElementById('quick-actions-bar')!.classList.contains('hidden')).toBe(true);
  });
});
