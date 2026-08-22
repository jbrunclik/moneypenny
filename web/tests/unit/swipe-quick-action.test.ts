/**
 * Unit tests for the configurable swipe quick action: which button is
 * surfaced next to ⋯ More when a conversation row is swiped on mobile.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { getSwipeQuickAction, setSwipeQuickAction } from '@/utils/preferences';
import { renderSwipeActions } from '@/components/Sidebar';

describe('swipe quick action preference', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults to archive', () => {
    expect(getSwipeQuickAction()).toBe('archive');
  });

  it('persists the chosen action', () => {
    setSwipeQuickAction('delete');
    expect(getSwipeQuickAction()).toBe('delete');
    setSwipeQuickAction('archive');
    expect(getSwipeQuickAction()).toBe('archive');
  });

  it('falls back to archive on garbage stored values', () => {
    localStorage.setItem('swipe_quick_action', 'explode');
    expect(getSwipeQuickAction()).toBe('archive');
  });
});

describe('renderSwipeActions', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('surfaces Archive by default, next to the More button', () => {
    const html = renderSwipeActions('conv-1');
    expect(html).toContain('data-more-id="conv-1"');
    expect(html).toContain('data-archive-id="conv-1"');
    expect(html).not.toContain('data-delete-id');
  });

  it('surfaces Delete when the preference says so', () => {
    setSwipeQuickAction('delete');
    const html = renderSwipeActions('conv-1');
    expect(html).toContain('data-more-id="conv-1"');
    expect(html).toContain('data-delete-id="conv-1"');
    expect(html).toContain('conversation-delete-swipe');
    expect(html).not.toContain('data-archive-id');
  });
});
