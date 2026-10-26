/**
 * Sync's view of the paginated sidebar list: a conversation belongs to the
 * loaded window when the whole list is loaded, or when it is at least as
 * recent as the oldest loaded unpinned row (pinned rows are never paged, so
 * they don't mark the boundary). A conversation is "pagination-discovered"
 * (old, not new) when it was last updated more than the buffer before the
 * first full sync; without that time or with a bad timestamp it is treated
 * as discovered, so no false unread badges appear.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { inLoadedWindow, isPaginationDiscovered } from '@/sync/pagination-window';
import type { Conversation } from '@/types/api';

function conv(id: string, updatedAt: string, pinned = false): Conversation {
  return { id, title: id, model: 'm', created_at: updatedAt, updated_at: updatedAt, pinned };
}

function loadList(conversations: Conversation[], hasMore: boolean): void {
  useStore.getState().setConversations(conversations, {
    has_more: hasMore,
    next_cursor: hasMore ? 'next' : null,
    total_count: 50,
  });
}

describe('inLoadedWindow', () => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  it('is true for anything when the whole list is loaded', () => {
    loadList([conv('a', '2026-10-20T00:00:00Z')], false);
    expect(inLoadedWindow('2020-01-01T00:00:00Z')).toBe(true);
  });

  it('is true when nothing unpinned is loaded yet', () => {
    loadList([conv('p', '2026-10-20T00:00:00Z', true)], true);
    expect(inLoadedWindow('2020-01-01T00:00:00Z')).toBe(true);
  });

  it('compares against the oldest loaded unpinned conversation', () => {
    loadList([conv('a', '2026-10-20T00:00:00Z'), conv('b', '2026-10-10T00:00:00Z')], true);
    expect(inLoadedWindow('2026-10-15T00:00:00Z')).toBe(true);
    expect(inLoadedWindow('2026-10-10T00:00:00Z')).toBe(true);
    expect(inLoadedWindow('2026-10-09T23:59:59Z')).toBe(false);
  });

  it('does not let an old pinned conversation widen the window', () => {
    loadList(
      [conv('a', '2026-10-20T00:00:00Z'), conv('b', '2026-10-10T00:00:00Z'), conv('p', '2025-01-01T00:00:00Z', true)],
      true
    );
    expect(inLoadedWindow('2026-01-01T00:00:00Z')).toBe(false);
  });
});

describe('isPaginationDiscovered', () => {
  const LOAD = '2026-10-20T12:00:00Z';

  it('treats everything as discovered before the first full sync', () => {
    expect(isPaginationDiscovered(null, '2026-10-20T12:00:00Z')).toBe(true);
  });

  it('is discovered when updated well before the first sync', () => {
    expect(isPaginationDiscovered(LOAD, '2026-10-20T11:00:00Z')).toBe(true);
  });

  it('is new when updated after the first sync', () => {
    expect(isPaginationDiscovered(LOAD, '2026-10-20T12:01:00Z')).toBe(false);
  });

  it('allows a few seconds of slack around the first sync', () => {
    expect(isPaginationDiscovered(LOAD, '2026-10-20T11:59:56Z')).toBe(false);
    expect(isPaginationDiscovered(LOAD, '2026-10-20T11:59:55Z')).toBe(false);
    expect(isPaginationDiscovered(LOAD, '2026-10-20T11:59:54Z')).toBe(true);
  });

  it('treats an unparseable timestamp as discovered', () => {
    expect(isPaginationDiscovered(LOAD, 'not a date')).toBe(true);
    expect(isPaginationDiscovered('garbage', '2026-10-20T12:01:00Z')).toBe(true);
  });
});
