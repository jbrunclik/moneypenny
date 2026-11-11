/**
 * mount/unmount of the quick-actions bar and the body marker class.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  mountQuickActionsBar,
  unmountQuickActionsBar,
  getQuickActionsContext,
  openQuickActionsEditor,
  reloadQuickActions,
} from '@/core/quick-actions';
import { closeQuickActionsEditor } from '@/components/QuickActionsEditor';

describe('quick actions mount', () => {
  beforeEach(() => {
    document.body.className = '';
    document.body.innerHTML = `
      <div class="input-area"><div class="input-wrapper">
        <div id="input-container">
          <div id="quick-actions-bar" class="quick-actions-bar hidden"></div>
          <div id="quick-action-mode" class="qa-mode hidden"></div>
          <div id="quick-action-slash" class="qa-slash-menu hidden"></div>
          <textarea id="message-input"></textarea>
        </div>
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

  it('reloadQuickActions refreshes the chips from the server (a card approved in chat)', async () => {
    const plan = { id: 'a', emoji: '📋', label: 'Plan', body: 'Plan.', fields: [] };
    const week = { id: 'w', emoji: '📅', label: 'Plan week', body: 'Week.', fields: [] };
    mountQuickActionsBar({
      namespace: 'sports',
      programId: 'pushups',
      actions: [plan],
      save: vi.fn(),
      load: vi.fn(() => Promise.resolve([plan, week])),
    });

    await reloadQuickActions();

    const bar = document.getElementById('quick-actions-bar')!;
    expect(bar.querySelectorAll('.quick-action-chip').length).toBe(2);
    expect(getQuickActionsContext()?.actions.map((a) => a.id)).toEqual(['a', 'w']);
  });

  it('the editor opens on the server copy, so an edit never resends a stale list', async () => {
    const plan = { id: 'a', emoji: '📋', label: 'Plan', body: 'Plan.', fields: [] };
    const week = { id: 'w', emoji: '📅', label: 'Plan week', body: 'Week.', fields: [] };
    mountQuickActionsBar({
      namespace: 'sports',
      programId: 'pushups',
      actions: [plan],
      save: vi.fn(),
      load: vi.fn(() => Promise.resolve([plan, week])),
    });

    await openQuickActionsEditor();

    expect(document.querySelectorAll('.qa-editor-row').length).toBe(2);
    closeQuickActionsEditor();
  });

  it('mount with zero actions still shows the bar with only the edit chip', () => {
    mountQuickActionsBar({ namespace: 'language', programId: 'es', actions: [], save: vi.fn() });
    const bar = document.getElementById('quick-actions-bar')!;
    expect(bar.classList.contains('hidden')).toBe(false);
    expect(bar.querySelectorAll('.quick-action-chip').length).toBe(0);
    expect(bar.querySelector('.quick-action-edit-chip')).not.toBeNull();
  });
});
