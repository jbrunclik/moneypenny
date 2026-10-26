/**
 * Trash slice: the trashed conversations shown in the trash view, sorted by
 * updated_at like the main list, with a total that follows every local add
 * and remove so the user-menu badge stays right between syncs.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { initialTrashData } from '@/state/slices/trash';
import type { Conversation, ConversationsPagination } from '@/types/api';

function conv(id: string, updatedAt: string): Conversation {
  return { id, title: id, model: 'm', created_at: updatedAt, updated_at: updatedAt };
}

function page(total: number, hasMore = false): ConversationsPagination {
  return { next_cursor: hasMore ? 'next' : null, has_more: hasMore, total_count: total };
}

const s = () => useStore.getState();
const ids = () => s().trashedConversations.map((c) => c.id);

describe('trash slice', () => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  it('starts empty and outside the trash view', () => {
    expect(s().trashedConversations).toEqual([]);
    expect(s().isTrashView).toBe(false);
    expect(s().isEmptyingTrash).toBe(false);
    expect(initialTrashData().trashPagination.totalCount).toBe(0);
  });

  it('replaces the list and its pagination', () => {
    s().setTrashedConversations([conv('a', '2026-10-02T00:00:00Z')], page(5, true));

    expect(ids()).toEqual(['a']);
    expect(s().trashPagination.totalCount).toBe(5);
    expect(s().trashPagination.hasMore).toBe(true);
  });

  it('appends a page without duplicates, keeping newest first', () => {
    s().setTrashedConversations([conv('b', '2026-10-02T00:00:00Z')], page(3, true));

    s().appendTrashedConversations(
      [conv('b', '2026-10-02T00:00:00Z'), conv('a', '2026-10-03T00:00:00Z'), conv('c', '2026-10-01T00:00:00Z')],
      page(3)
    );

    expect(ids()).toEqual(['a', 'b', 'c']);
    expect(s().trashPagination.hasMore).toBe(false);
  });

  it('adds a trashed conversation at its sorted place and counts it', () => {
    s().setTrashedConversations(
      [conv('new', '2026-10-03T00:00:00Z'), conv('old', '2026-10-01T00:00:00Z')],
      page(2)
    );

    s().addTrashedConversation(conv('mid', '2026-10-02T00:00:00Z'));

    expect(ids()).toEqual(['new', 'mid', 'old']);
    expect(s().trashPagination.totalCount).toBe(3);
  });

  it('removes a conversation (restored or deleted for good) and never counts below zero', () => {
    s().setTrashedConversations([conv('a', '2026-10-01T00:00:00Z')], page(1));

    s().removeTrashedConversation('a');
    s().removeTrashedConversation('a');

    expect(ids()).toEqual([]);
    expect(s().trashPagination.totalCount).toBe(0);
  });

  it('clears everything after emptying the trash', () => {
    s().setTrashedConversations([conv('a', '2026-10-01T00:00:00Z')], page(4, true));

    s().clearTrash();

    expect(ids()).toEqual([]);
    expect(s().trashPagination.totalCount).toBe(0);
    expect(s().trashPagination.hasMore).toBe(false);
  });

  it('tracks the view, the empty-trash request and loading more', () => {
    s().setIsTrashView(true);
    s().setEmptyingTrash(true);
    s().setLoadingMoreTrash(true);

    expect(s().isTrashView).toBe(true);
    expect(s().isEmptyingTrash).toBe(true);
    expect(s().trashPagination.isLoadingMore).toBe(true);
  });
});
