/**
 * Delivery state of a user message: each send gets one automatic retry per
 * session (a manual retry or a confirmed delivery earns a fresh one); a
 * confirmed delivery drops the outbox entry and clears the pending chrome; a
 * failure flags the message as "Not sent" - but only while it is still
 * unconfirmed, so a mid-stream error after delivery leaves it alone.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { claimAutoRetry, confirmDelivery, markSendFailed, resetAutoRetry } from '@/core/send-delivery';
import { _clearOutboxMemoryCache, addOutboxEntry, getOutboxEntry } from '@/core/outbox';
import { useStore } from '@/state/store';
import type { Message } from '@/types/api';

const CONV = 'conv-1';

// The retry budget is session state shared by the whole module: every test
// uses its own message id so they stay independent
let seq = 0;
function freshId(): string {
  seq += 1;
  return `msg-${seq}`;
}

function messageFor(id: string): Message | undefined {
  return useStore
    .getState()
    .getMessages(CONV)
    .find((m) => m.id === id);
}

/** A send in flight: outbox entry, pending message in the store and the DOM. */
function startSend(id: string): HTMLElement {
  addOutboxEntry({
    id,
    conversationId: CONV,
    content: `text ${id}`,
    files: [],
    forceTools: [],
    anonymousMode: false,
    createdAt: '2026-10-26T10:00:00.000Z',
  });
  useStore.getState().appendMessage(CONV, {
    id,
    role: 'user',
    content: `text ${id}`,
    created_at: '2026-10-26T10:00:00.000Z',
    status: 'pending',
  });
  const el = document.createElement('div');
  el.className = 'message user message--send-pending';
  el.dataset.messageId = id;
  const wrapper = document.createElement('div');
  wrapper.className = 'message-content-wrapper';
  el.appendChild(wrapper);
  document.body.appendChild(el);
  return el;
}

beforeEach(() => {
  localStorage.clear();
  _clearOutboxMemoryCache();
  document.body.innerHTML = '';
  useStore.setState({ messages: new Map(), messagesPagination: new Map() });
});

describe('claimAutoRetry', () => {
  it('grants the first automatic retry for a send', () => {
    expect(claimAutoRetry(freshId())).toBe(true);
  });

  it('refuses a second automatic retry for the same send', () => {
    const id = freshId();
    claimAutoRetry(id);
    expect(claimAutoRetry(id)).toBe(false);
  });

  it('keeps a separate budget for each send', () => {
    const first = freshId();
    claimAutoRetry(first);
    expect(claimAutoRetry(freshId())).toBe(true);
  });
});

describe('resetAutoRetry', () => {
  it('earns a fresh automatic retry after a manual retry', () => {
    const id = freshId();
    claimAutoRetry(id);
    resetAutoRetry(id);
    expect(claimAutoRetry(id)).toBe(true);
  });

  it('is harmless for a send that never used its retry', () => {
    const id = freshId();
    resetAutoRetry(id);
    expect(claimAutoRetry(id)).toBe(true);
  });
});

describe('confirmDelivery', () => {
  it('drops the outbox entry', () => {
    const id = freshId();
    startSend(id);
    confirmDelivery(CONV, id);
    expect(getOutboxEntry(CONV, id)).toBeUndefined();
  });

  it('clears the pending status in the store', () => {
    const id = freshId();
    startSend(id);
    confirmDelivery(CONV, id);
    expect(messageFor(id)?.status).toBeUndefined();
  });

  it('removes the pending chrome from the rendered message', () => {
    const id = freshId();
    const el = startSend(id);
    confirmDelivery(CONV, id);
    expect(el.classList.contains('message--send-pending')).toBe(false);
    expect(el.classList.contains('message--send-failed')).toBe(false);
  });

  it('removes the "Not sent" row of a message that failed earlier', () => {
    const id = freshId();
    const el = startSend(id);
    markSendFailed(CONV, id);
    confirmDelivery(CONV, id);
    expect(el.querySelector('.message-send-status')).toBeNull();
  });

  it('gives the message a fresh automatic retry for a later failure', () => {
    const id = freshId();
    startSend(id);
    claimAutoRetry(id);
    confirmDelivery(CONV, id);
    expect(claimAutoRetry(id)).toBe(true);
  });
});

describe('markSendFailed', () => {
  it('marks the outbox entry as failed', () => {
    const id = freshId();
    startSend(id);
    markSendFailed(CONV, id);
    expect(getOutboxEntry(CONV, id)?.status).toBe('failed');
  });

  it('marks the message as failed in the store', () => {
    const id = freshId();
    startSend(id);
    markSendFailed(CONV, id);
    expect(messageFor(id)?.status).toBe('failed');
  });

  it('shows the "Not sent" row with retry and discard on the rendered message', () => {
    const id = freshId();
    const el = startSend(id);
    markSendFailed(CONV, id);
    expect(el.classList.contains('message--send-failed')).toBe(true);
    expect(el.classList.contains('message--send-pending')).toBe(false);
    const actions = [...el.querySelectorAll<HTMLElement>('.message-send-status [data-action]')];
    expect(actions.map((b) => b.dataset.action)).toEqual(['retry-send', 'discard-send']);
  });

  it('leaves an already delivered message alone (mid-stream failure after delivery)', () => {
    const id = freshId();
    const el = startSend(id);
    confirmDelivery(CONV, id);
    markSendFailed(CONV, id);
    expect(messageFor(id)?.status).toBeUndefined();
    expect(el.classList.contains('message--send-failed')).toBe(false);
    expect(el.querySelector('.message-send-status')).toBeNull();
    expect(getOutboxEntry(CONV, id)).toBeUndefined();
  });

  it('adds only one "Not sent" row when a send fails twice', () => {
    const id = freshId();
    const el = startSend(id);
    markSendFailed(CONV, id);
    markSendFailed(CONV, id);
    expect(el.querySelectorAll('.message-send-status')).toHaveLength(1);
  });
});
