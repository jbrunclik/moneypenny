/**
 * Messages slice: per-conversation message lists and their pagination.
 * The total count must follow every local append/remove/truncate so the
 * "load more" math and sync counts stay right.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { initialMessagesData, type MessagesPaginationState } from '@/state/slices/messages';
import type { Message, MessagesPagination } from '@/types/api';

function at<T>(items: ArrayLike<T>, i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item at index ${i}`);
  return item;
}

function msg(id: string, role: Message['role'] = 'user'): Message {
  return { id, role, content: id, created_at: '2026-10-01T00:00:00Z' };
}

function page(total: number, overrides: Partial<MessagesPagination> = {}): MessagesPagination {
  return {
    older_cursor: null,
    newer_cursor: null,
    has_older: false,
    has_newer: false,
    total_count: total,
    ...overrides,
  };
}

const ids = (convId: string) => useStore.getState().getMessages(convId).map((m) => m.id);
const total = (convId: string) => useStore.getState().getMessagesPagination(convId)?.totalCount;

describe('messages slice', () => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  it('starts with no messages or pagination', () => {
    expect(initialMessagesData()).toEqual({ messages: new Map(), messagesPagination: new Map() });
    expect(useStore.getState().messages.size).toBe(0);
  });

  describe('pages', () => {
    it('setMessages stores the list and maps the pagination', () => {
      useStore.getState().setMessages('c1', [msg('m1')], page(5, { older_cursor: 'o', has_older: true }));
      expect(ids('c1')).toEqual(['m1']);
      const expected: MessagesPaginationState = {
        olderCursor: 'o',
        newerCursor: null,
        hasOlder: true,
        hasNewer: false,
        totalCount: 5,
        isLoadingOlder: false,
        isLoadingNewer: false,
      };
      expect(useStore.getState().getMessagesPagination('c1')).toEqual(expected);
    });

    it('prependMessages puts an older page in front and replaces the cursors', () => {
      const store = useStore.getState();
      store.setMessages('c1', [msg('m3')], page(3, { older_cursor: 'o1', has_older: true }));
      store.setLoadingOlderMessages('c1', true);
      store.prependMessages('c1', [msg('m1'), msg('m2')], page(3));
      expect(ids('c1')).toEqual(['m1', 'm2', 'm3']);
      const pag = useStore.getState().getMessagesPagination('c1');
      expect(pag?.hasOlder).toBe(false);
      expect(pag?.isLoadingOlder).toBe(false);
    });

    it('appendMessages puts a newer page at the end', () => {
      const store = useStore.getState();
      store.setMessages('c1', [msg('m1')], page(3, { has_newer: true }));
      store.appendMessages('c1', [msg('m2'), msg('m3')], page(3));
      expect(ids('c1')).toEqual(['m1', 'm2', 'm3']);
    });

    it('keeps conversations separate', () => {
      const store = useStore.getState();
      store.setMessages('c1', [msg('a')], page(1));
      store.setMessages('c2', [msg('b')], page(1));
      expect(ids('c1')).toEqual(['a']);
      expect(ids('c2')).toEqual(['b']);
    });

    it('getMessages returns an empty list for an unknown conversation', () => {
      expect(useStore.getState().getMessages('nope')).toEqual([]);
      expect(useStore.getState().getMessagesPagination('nope')).toBeUndefined();
    });
  });

  describe('appendMessage', () => {
    it('appends and bumps the total', () => {
      useStore.getState().setMessages('c1', [msg('m1')], page(1));
      useStore.getState().appendMessage('c1', msg('m2'));
      expect(ids('c1')).toEqual(['m1', 'm2']);
      expect(total('c1')).toBe(2);
    });

    it('inserts before the given message', () => {
      useStore.getState().setMessages('c1', [msg('m1'), msg('reply', 'assistant')], page(2));
      useStore.getState().appendMessage('c1', msg('steer'), 'reply');
      expect(ids('c1')).toEqual(['m1', 'steer', 'reply']);
      expect(total('c1')).toBe(3);
    });

    it('appends at the end when the beforeId is unknown', () => {
      useStore.getState().setMessages('c1', [msg('m1')], page(1));
      useStore.getState().appendMessage('c1', msg('m2'), 'missing');
      expect(ids('c1')).toEqual(['m1', 'm2']);
    });

    it('replaces a message with the same id in place without changing the total', () => {
      useStore.getState().setMessages('c1', [msg('m1'), msg('r1', 'assistant'), msg('m2')], page(3));
      useStore.getState().appendMessage('c1', { ...msg('r1', 'assistant'), content: 'final' });
      expect(ids('c1')).toEqual(['m1', 'r1', 'm2']);
      expect(useStore.getState().getMessages('c1')[1]?.content).toBe('final');
      expect(total('c1')).toBe(3);
    });

    it('works for a conversation that has no pagination yet', () => {
      useStore.getState().appendMessage('fresh', msg('m1'));
      expect(ids('fresh')).toEqual(['m1']);
      expect(useStore.getState().getMessagesPagination('fresh')).toBeUndefined();
    });
  });

  describe('updateMessage / removeMessage', () => {
    it('updateMessage merges fields into the matching message only', () => {
      useStore.getState().setMessages('c1', [msg('m1'), msg('m2')], page(2));
      useStore.getState().updateMessage('c1', 'm2', { status: 'failed' });
      const msgs = useStore.getState().getMessages('c1');
      const m1 = at(msgs, 0);
      const m2 = at(msgs, 1);
      expect(m1.status).toBeUndefined();
      expect(m2.status).toBe('failed');
    });

    it('updateMessage for an unknown id leaves the state untouched', () => {
      useStore.getState().setMessages('c1', [msg('m1')], page(1));
      const before = useStore.getState().messages;
      useStore.getState().updateMessage('c1', 'nope', { content: 'x' });
      expect(useStore.getState().messages).toBe(before);
    });

    it('removeMessage drops the message and decrements the total', () => {
      useStore.getState().setMessages('c1', [msg('m1'), msg('m2')], page(2));
      useStore.getState().removeMessage('c1', 'm1');
      expect(ids('c1')).toEqual(['m2']);
      expect(total('c1')).toBe(1);
    });

    it('removeMessage never drives the total below zero', () => {
      useStore.getState().setMessages('c1', [msg('m1')], page(0));
      useStore.getState().removeMessage('c1', 'm1');
      expect(total('c1')).toBe(0);
    });

    it('removeMessage for an unknown id does not change the total', () => {
      useStore.getState().setMessages('c1', [msg('m1')], page(1));
      useStore.getState().removeMessage('c1', 'nope');
      expect(total('c1')).toBe(1);
    });
  });

  describe('truncateMessagesFrom', () => {
    it('removes the message and everything after it, adjusting the total', () => {
      useStore.getState().setMessages('c1', [msg('a'), msg('b'), msg('c'), msg('d')], page(10));
      useStore.getState().truncateMessagesFrom('c1', 'c');
      expect(ids('c1')).toEqual(['a', 'b']);
      expect(total('c1')).toBe(8);
    });

    it('is a no-op for an unknown id', () => {
      useStore.getState().setMessages('c1', [msg('a')], page(1));
      useStore.getState().truncateMessagesFrom('c1', 'nope');
      expect(ids('c1')).toEqual(['a']);
      expect(total('c1')).toBe(1);
    });
  });

  describe('clearMessages and loading flags', () => {
    it('clearMessages drops the list and the pagination', () => {
      useStore.getState().setMessages('c1', [msg('a')], page(1));
      useStore.getState().clearMessages('c1');
      expect(useStore.getState().messages.has('c1')).toBe(false);
      expect(useStore.getState().messagesPagination.has('c1')).toBe(false);
    });

    it('sets the older/newer loading flags independently', () => {
      useStore.getState().setMessages('c1', [], page(0));
      useStore.getState().setLoadingOlderMessages('c1', true);
      expect(useStore.getState().getMessagesPagination('c1')).toMatchObject({
        isLoadingOlder: true,
        isLoadingNewer: false,
      });
      useStore.getState().setLoadingNewerMessages('c1', true);
      useStore.getState().setLoadingOlderMessages('c1', false);
      expect(useStore.getState().getMessagesPagination('c1')).toMatchObject({
        isLoadingOlder: false,
        isLoadingNewer: true,
      });
    });

    it('a loading flag for a conversation without pagination is ignored', () => {
      useStore.getState().setLoadingOlderMessages('nope', true);
      expect(useStore.getState().getMessagesPagination('nope')).toBeUndefined();
    });
  });
});
