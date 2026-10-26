/**
 * Waiting for the reply to a user message this page is no longer reading
 * (send 409, batch turn after reload): refetch on a fixed schedule until an
 * assistant message follows it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Conversation, Message } from '@/types/api';

const { get, renderMessages, showLoadingIndicator } = vi.hoisted(() => ({
  get: vi.fn(),
  renderMessages: vi.fn(),
  showLoadingIndicator: vi.fn(),
}));
vi.mock('@/api/conversations', () => ({ conversations: { get } }));
vi.mock('@/components/messages', () => ({ renderMessages, showLoadingIndicator }));
vi.mock('@/core/outbox', () => ({
  reconcileOutboxWithServer: (_convId: string, messages: Message[]) => messages,
}));

import { SEND_CONFLICT_REPLY_POLL_DELAYS_MS } from '@/config';
import { waitForReplyTo } from '@/core/reply-wait';
import { useStore } from '@/state/store';

function at<T>(items: ArrayLike<T>, i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item at index ${i}`);
  return item;
}

function msg(id: string, role: Message['role']): Message {
  return { id, role, content: id, created_at: '2026-10-26T10:00:00Z' };
}

function serverResponse(messages: Message[]) {
  return {
    messages,
    has_pending_approval: false,
    message_pagination: { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: messages.length },
  };
}

function openConversation(id: string): void {
  const conv: Conversation = { id, title: id, model: 'm', created_at: '', updated_at: '' };
  useStore.getState().setCurrentConversation(conv);
}

const TOTAL_POLL_MS = SEND_CONFLICT_REPLY_POLL_DELAYS_MS.reduce((a, b) => a + b, 0);

describe('waitForReplyTo', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useStore.setState(useStore.getInitialState(), true);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns at once when the reply is already on the server', async () => {
    openConversation('c1');
    get.mockResolvedValue(serverResponse([msg('m1', 'user'), msg('r1', 'assistant')]));
    await expect(waitForReplyTo('c1', 'm1')).resolves.toBe(true);
    expect(get).toHaveBeenCalledTimes(1);
    expect(useStore.getState().getMessages('c1').map((m) => m.id)).toEqual(['m1', 'r1']);
    expect(renderMessages).toHaveBeenCalledTimes(1);
    expect(showLoadingIndicator).not.toHaveBeenCalled();
  });

  it('keeps the spinner up and polls until the reply lands', async () => {
    openConversation('c1');
    get
      .mockResolvedValueOnce(serverResponse([msg('m1', 'user')]))
      .mockResolvedValueOnce(serverResponse([msg('m1', 'user'), msg('r1', 'assistant')]));
    const result = waitForReplyTo('c1', 'm1');
    await vi.advanceTimersByTimeAsync(at(SEND_CONFLICT_REPLY_POLL_DELAYS_MS, 0));
    await expect(result).resolves.toBe(true);
    expect(get).toHaveBeenCalledTimes(2);
    expect(showLoadingIndicator).toHaveBeenCalledTimes(1);
  });

  it('an assistant message BEFORE the user message is not the reply', async () => {
    get.mockResolvedValue(serverResponse([msg('r0', 'assistant'), msg('m1', 'user')]));
    const result = waitForReplyTo('c1', 'm1');
    await vi.advanceTimersByTimeAsync(TOTAL_POLL_MS);
    await expect(result).resolves.toBe(false);
  });

  it('gives up after the poll schedule runs out', async () => {
    get.mockResolvedValue(serverResponse([msg('m1', 'user')]));
    const result = waitForReplyTo('c1', 'm1');
    await vi.advanceTimersByTimeAsync(TOTAL_POLL_MS);
    await expect(result).resolves.toBe(false);
    expect(get).toHaveBeenCalledTimes(SEND_CONFLICT_REPLY_POLL_DELAYS_MS.length + 1);
  });

  it('a failed refetch counts as no reply yet and polling continues', async () => {
    get
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(serverResponse([msg('m1', 'user'), msg('r1', 'assistant')]));
    const result = waitForReplyTo('c1', 'm1');
    await vi.advanceTimersByTimeAsync(at(SEND_CONFLICT_REPLY_POLL_DELAYS_MS, 0));
    await expect(result).resolves.toBe(true);
  });

  it('updates the store but does not render when another conversation is open', async () => {
    openConversation('other');
    get.mockResolvedValue(serverResponse([msg('m1', 'user'), msg('r1', 'assistant')]));
    await waitForReplyTo('c1', 'm1');
    expect(useStore.getState().getMessages('c1')).toHaveLength(2);
    expect(renderMessages).not.toHaveBeenCalled();
  });
});
