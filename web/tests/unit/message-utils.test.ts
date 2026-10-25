/**
 * Shared Messages helpers: the timestamp under a message (time today,
 * "Yesterday HH:MM", a date before that) and swapping a sent message's
 * temporary id for the server id across its DOM.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const { updateChatHeaderTitle } = vi.hoisted(() => ({ updateChatHeaderTitle: vi.fn() }));
vi.mock('@/components/ChatHeader', () => ({ updateChatHeaderTitle }));

import { formatMessageTime, updateChatTitle, updateUserMessageId } from '@/components/messages/utils';

const timeOf = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
// The localized word for "yesterday" in the runner's locale
const YESTERDAY = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(-1, 'day');

/**
 * The first local midnight in 2026 that follows a day which was not 24 hours
 * long (the day after a DST change), or null in a zone without DST.
 */
function midnightAfterDstChange(): Date | null {
  for (let day = 1; day < 365; day++) {
    const start = new Date(2026, 0, day);
    const next = new Date(2026, 0, day + 1);
    if (next.getTime() - start.getTime() !== 24 * 60 * 60 * 1000) return next;
  }
  return null;
}

describe('formatMessageTime', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows only the time for a message from today', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 15, 18, 0));
    const sent = new Date(2026, 5, 15, 9, 5);
    expect(formatMessageTime(sent.toISOString())).toBe(timeOf(sent));
  });

  it('prefixes the time with "yesterday" for a message from the previous day', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 15, 8, 0));
    const sent = new Date(2026, 5, 14, 23, 30);
    expect(formatMessageTime(sent.toISOString())).toBe(`${YESTERDAY} ${timeOf(sent)}`);
  });

  it('shows a date for older messages', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 15, 8, 0));
    const sent = new Date(2026, 5, 10, 12, 0);
    const text = formatMessageTime(sent.toISOString());
    expect(text).not.toBe(timeOf(sent));
    expect(text).not.toContain(YESTERDAY);
    expect(text).toContain('10');
  });

  // BUG: "yesterday" is computed as today's midnight minus 24 hours. The day
  // after a DST change that lands an hour off midnight, so messages from the
  // previous day show a full date instead of "Yesterday HH:MM". Only
  // observable in a time zone with DST (skipped in UTC, e.g. CI).
  const dstMidnight = midnightAfterDstChange();
  it.skipIf(dstMidnight === null).fails('still says "yesterday" on the day after a DST change', () => {
    if (!dstMidnight) return;
    vi.useFakeTimers();
    vi.setSystemTime(new Date(dstMidnight.getTime() + 12 * 60 * 60 * 1000));
    const sent = new Date(dstMidnight.getFullYear(), dstMidnight.getMonth(), dstMidnight.getDate() - 1, 12, 0);
    expect(formatMessageTime(sent.toISOString())).toBe(`${YESTERDAY} ${timeOf(sent)}`);
  });
});

describe('updateChatTitle', () => {
  it('updates the mobile title and the desktop header', () => {
    document.body.innerHTML = '<span id="current-chat-title">Old</span>';
    updateChatTitle('New title');
    expect(document.getElementById('current-chat-title')?.textContent).toBe('New title');
    expect(updateChatHeaderTitle).toHaveBeenCalledWith('New title');
  });
});

describe('updateUserMessageId', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="messages">
        <div class="message user" data-message-id="temp-1">
          <img data-message-id="temp-1" data-pending="true">
          <button class="file-download" data-message-id="temp-1"></button>
        </div>
        <div class="message assistant" data-message-id="temp-1-other"></div>
      </div>`;
  });

  const el = (selector: string) => document.querySelector<HTMLElement>(selector);

  it('moves the message and its attachments to the real id', () => {
    updateUserMessageId('temp-1', 'real-1');
    expect(el('.message.user')?.dataset.messageId).toBe('real-1');
    expect(el('img')?.dataset.messageId).toBe('real-1');
    expect(el('.file-download')?.dataset.messageId).toBe('real-1');
  });

  it('enables the lightbox on its images (drops the pending flag)', () => {
    updateUserMessageId('temp-1', 'real-1');
    expect(el('img')?.dataset.pending).toBeUndefined();
  });

  it('leaves other messages alone', () => {
    updateUserMessageId('temp-1', 'real-1');
    expect(el('.message.assistant')?.dataset.messageId).toBe('temp-1-other');
  });

  it('is idempotent once the real id is in place', () => {
    updateUserMessageId('temp-1', 'real-1');
    updateUserMessageId('temp-1', 'real-1');
    expect(document.querySelectorAll('[data-message-id="real-1"]')).toHaveLength(3);
  });

  it('does nothing for an unknown temporary id', () => {
    updateUserMessageId('temp-404', 'real-1');
    expect(el('.message.user')?.dataset.messageId).toBe('temp-1');
  });
});
