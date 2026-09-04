/**
 * Component tests for the "/" quick-actions menu.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  filterQuickActions,
  renderSlashMenu,
  clearSlashMenu,
} from '@/components/QuickActionsSlashMenu';
import type { QuickAction } from '@/types/api';

const actions: QuickAction[] = [
  { id: 'a', emoji: '📋', label: 'Plan today', body: 'Plan my session.', fields: [] },
  { id: 'b', emoji: '📊', label: 'Log & review', body: 'Review against the plan.', fields: ['RPE'] },
];

describe('filterQuickActions', () => {
  it('returns everything for an empty filter', () => {
    expect(filterQuickActions(actions, '')).toEqual(actions);
  });
  it('matches label or body, case-insensitively', () => {
    expect(filterQuickActions(actions, 'LOG').map((a) => a.id)).toEqual(['b']);
    expect(filterQuickActions(actions, 'plan').map((a) => a.id)).toEqual(['a', 'b']);
    expect(filterQuickActions(actions, 'zzz')).toEqual([]);
  });
});

describe('renderSlashMenu', () => {
  let container: HTMLElement;
  beforeEach(() => {
    document.body.innerHTML = '<div id="quick-action-slash" class="qa-slash-menu hidden"></div>';
    container = document.getElementById('quick-action-slash')!;
  });

  it('renders items, marks the active one, and picks on click', () => {
    const onPick = vi.fn();
    renderSlashMenu(container, actions, 1, onPick);
    expect(container.classList.contains('hidden')).toBe(false);
    const items = container.querySelectorAll('.qa-slash-item');
    expect(items.length).toBe(2);
    expect(items[1].classList.contains('active')).toBe(true);
    expect(items[1].getAttribute('aria-selected')).toBe('true');
    (items[0].querySelector('.qa-slash-label') as HTMLElement).click();
    expect(onPick).toHaveBeenCalledWith(actions[0]);
  });

  it('hides when there are no items and clear empties it', () => {
    renderSlashMenu(container, [], 0, vi.fn());
    expect(container.classList.contains('hidden')).toBe(true);
    renderSlashMenu(container, actions, 0, vi.fn());
    clearSlashMenu(container);
    expect(container.children.length).toBe(0);
    expect(container.classList.contains('hidden')).toBe(true);
  });
});
