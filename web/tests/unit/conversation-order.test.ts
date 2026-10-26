/**
 * Conversation ordering helpers shared by the conversations, archive and
 * trash slices: the sidebar renders the array in order, so every insert must
 * keep it sorted by updated_at DESC.
 */
import { describe, it, expect, afterAll, afterEach, beforeAll, vi } from 'vitest';
import {
  appendSortedByUpdatedAt,
  emptyConversationsPagination,
  insertSortedByUpdatedAt,
  localIsoNow,
  toConversationsPaginationState,
} from '@/state/slices/conversationOrder';
import type { Conversation } from '@/types/api';
import { compareTimestamps } from '@/utils/timestamps';

function conv(id: string, updatedAt: string): Conversation {
  return { id, title: id, model: 'm', created_at: updatedAt, updated_at: updatedAt };
}

const ids = (list: Conversation[]) => list.map((c) => c.id);

describe('insertSortedByUpdatedAt', () => {
  const list = [conv('a', '2026-10-03T00:00:00'), conv('b', '2026-10-02T00:00:00'), conv('c', '2026-10-01T00:00:00')];

  it('inserts in the middle by timestamp', () => {
    expect(ids(insertSortedByUpdatedAt(list, conv('x', '2026-10-02T12:00:00')))).toEqual(['a', 'x', 'b', 'c']);
  });

  it('puts the newest first and the oldest last', () => {
    expect(ids(insertSortedByUpdatedAt(list, conv('new', '2026-10-04T00:00:00')))[0]).toBe('new');
    expect(ids(insertSortedByUpdatedAt(list, conv('old', '2026-09-30T00:00:00'))).at(-1)).toBe('old');
  });

  it('puts a conversation with an equal timestamp BEFORE the existing one', () => {
    expect(ids(insertSortedByUpdatedAt(list, conv('tie', '2026-10-02T00:00:00')))).toEqual(['a', 'tie', 'b', 'c']);
  });

  it('inserts into an empty list', () => {
    expect(ids(insertSortedByUpdatedAt([], conv('only', '2026-10-01T00:00:00')))).toEqual(['only']);
  });

  it('does not mutate the input list', () => {
    const before = [...list];
    insertSortedByUpdatedAt(list, conv('x', '2026-10-02T12:00:00'));
    expect(list).toEqual(before);
  });
});

describe('appendSortedByUpdatedAt', () => {
  it('puts a conversation with an equal timestamp AFTER the existing ones (server page order)', () => {
    const list = [conv('a', '2026-10-02T00:00:00'), conv('b', '2026-10-02T00:00:00'), conv('c', '2026-10-01T00:00:00')];
    expect(ids(appendSortedByUpdatedAt(list, conv('tie', '2026-10-02T00:00:00')))).toEqual(['a', 'b', 'tie', 'c']);
  });

  it('keeps a whole page of equal timestamps in server order when reduced in', () => {
    const page = [conv('p1', '2026-10-01T00:00:00'), conv('p2', '2026-10-01T00:00:00'), conv('p3', '2026-10-01T00:00:00')];
    expect(ids(page.reduce(appendSortedByUpdatedAt, [] as Conversation[]))).toEqual(['p1', 'p2', 'p3']);
  });

  it('still places a newer conversation ahead of older ones', () => {
    const list = [conv('old', '2026-10-01T00:00:00')];
    expect(ids(appendSortedByUpdatedAt(list, conv('new', '2026-10-05T00:00:00')))).toEqual(['new', 'old']);
  });
});

describe('ordering optimistic "Z" timestamps against server local-naive ones', () => {
  // The server sends local-naive strings; optimistic entries use toISOString().
  // Pinned to the household timezone (UTC+1 on this date) so the text order
  // and the instant order differ on any machine.
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = 'Europe/Prague';
  });
  afterAll(() => {
    process.env.TZ = originalTz;
  });

  // 12:30 and 11:30 Prague, as the server sends them
  const server = () => [conv('later', '2026-10-26T12:30:00.123456'), conv('earlier', '2026-10-26T11:30:00.654321')];
  // 12:00 Prague, created on this device: "2026-10-26T11:00:00.000Z"
  const optimistic = () => conv('opt', new Date(2026, 9, 26, 12, 0, 0).toISOString());

  it('inserts the optimistic entry between the server ones by instant', () => {
    expect(ids(insertSortedByUpdatedAt(server(), optimistic()))).toEqual(['later', 'opt', 'earlier']);
  });

  it('appends the optimistic entry between the server ones by instant', () => {
    expect(ids(appendSortedByUpdatedAt(server(), optimistic()))).toEqual(['later', 'opt', 'earlier']);
  });

  it('places a fresh server bump ahead of an optimistic entry from a moment earlier', () => {
    const list = [optimistic()];
    expect(ids(insertSortedByUpdatedAt(list, conv('bump', '2026-10-26T12:00:01')))).toEqual(['bump', 'opt']);
  });
});

describe('pagination state', () => {
  it('starts empty', () => {
    expect(emptyConversationsPagination()).toEqual({
      nextCursor: null,
      hasMore: false,
      totalCount: 0,
      isLoadingMore: false,
    });
  });

  it('maps the server pagination and resets the loading flag', () => {
    expect(toConversationsPaginationState({ next_cursor: 'cur', has_more: true, total_count: 42 })).toEqual({
      nextCursor: 'cur',
      hasMore: true,
      totalCount: 42,
      isLoadingMore: false,
    });
  });
});

describe('localIsoNow', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('formats LOCAL time without a timezone suffix, zero-padded with milliseconds', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 5, 7, 8, 9, 45)); // local time
    expect(localIsoNow()).toBe('2026-01-05T07:08:09.045');
  });

  it('orders against backend-style timestamps, as text and as instants', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 26, 12, 0, 0, 0));
    expect(localIsoNow() > '2026-10-26T11:59:59.999').toBe(true);
    expect(localIsoNow() < '2026-10-26T12:00:00.001').toBe(true);
    expect(compareTimestamps(localIsoNow(), '2026-10-26T11:59:59.999')).toBeGreaterThan(0);
    expect(compareTimestamps(localIsoNow(), new Date(2026, 9, 26, 12, 0, 0, 1).toISOString())).toBeLessThan(0);
  });
});
