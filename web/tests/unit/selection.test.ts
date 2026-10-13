/**
 * Selection slice: picking chats for bulk delete, select-all with
 * exclusions, the counter, and the request it builds.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import {
  buildBulkTrashRequest,
  isConversationSelected,
  selectedCount,
  selectedLoadedIds,
} from '@/state/slices/selection';
import type { Conversation } from '@/types/api';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}

const s = () => useStore.getState();

beforeEach(() => {
  useStore.setState({
    conversations: [conv('p', { pinned: true }), conv('a'), conv('b'), conv('temp-1')],
    conversationsPagination: { nextCursor: 'x', hasMore: true, totalCount: 10, isLoadingMore: false },
  });
  s().endSelection();
});

describe('selection', () => {
  it('toggles hand-picked rows and counts them', () => {
    s().startSelection();
    s().toggleSelected(conv('a'));
    s().toggleSelected(conv('b'));
    s().toggleSelected(conv('b'));

    expect(isConversationSelected(s(), conv('a'))).toBe(true);
    expect(isConversationSelected(s(), conv('b'))).toBe(false);
    expect(selectedCount(s())).toBe(1);
    expect(buildBulkTrashRequest(s())).toEqual({ ids: ['a'] });
  });

  it('leaves temp chats out of the request', () => {
    s().startSelection();
    s().toggleSelected(conv('temp-1'));

    expect(buildBulkTrashRequest(s())).toBeNull();
    expect(selectedLoadedIds(s())).toEqual(['temp-1']);
  });

  it('select all covers unpinned chats, counts the server total, and honours exclusions', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    s().toggleSelected(conv('a'));

    expect(isConversationSelected(s(), conv('p', { pinned: true }))).toBe(false);
    expect(isConversationSelected(s(), conv('a'))).toBe(false);
    expect(isConversationSelected(s(), conv('b'))).toBe(true);
    // 10 total - 1 pinned - 1 excluded
    expect(selectedCount(s())).toBe(8);
    expect(buildBulkTrashRequest(s())).toEqual({
      all: true,
      ids: [],
      exclude_ids: ['a'],
      created_before: '2026-10-13T10:00:00.000Z',
    });
  });

  it('a pinned chat ticked in select-all mode rides along in ids', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    s().toggleSelected(conv('p', { pinned: true }));

    expect(selectedCount(s())).toBe(10);
    expect(buildBulkTrashRequest(s())?.ids).toEqual(['p']);
  });

  it('rows loaded later are selected in all mode', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    useStore.setState({ conversations: [...s().conversations, conv('late')] });

    expect(isConversationSelected(s(), conv('late'))).toBe(true);
  });

  it('deselect all and end clear everything', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    s().deselectAll();
    expect(selectedCount(s())).toBe(0);
    expect(s().selectionMode).toBe('ids');

    s().toggleSelected(conv('a'));
    s().endSelection();
    expect(s().isSelecting).toBe(false);
    expect(s().selectedIds.size).toBe(0);
  });
});
