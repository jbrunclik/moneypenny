/**
 * Failed sends are resent when the connection returns, the app comes back
 * into view, or their conversation opens (Nov 16 2026: the offline toast
 * promised it, nothing did it).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  addOutboxEntry,
  markOutboxFailed,
  failedEntries,
  removeOutboxEntry,
  _clearOutboxMemoryCache,
} from '@/core/outbox';
import {
  OUTBOX_RESEND_BACKOFF_MS,
  OUTBOX_RESEND_DELAY_MS,
  OUTBOX_RESEND_MAX_AGE_MS,
  OUTBOX_STORAGE_KEY,
  OUTBOX_TABS_STORAGE_KEY,
} from '@/config';
import { useStore } from '@/state/store';

const sent: string[] = [];
let release: (() => void) | null = null;

const stillFails = new Set<string>();

vi.mock('@/core/rerun', () => ({
  resendOutboxEntry: vi.fn(async (convId: string, id: string) => {
    sent.push(id);
    // A send that lands is confirmed (gone from the outbox); a failing one stays failed
    if (!stillFails.has(id)) removeOutboxEntry(convId, id);
    if (release === null) return;
    await new Promise<void>((resolve) => {
      release = resolve;
    });
  }),
}));

const info = vi.fn();
vi.mock('@/components/Toast', () => ({ toast: { info: (m: string) => info(m) } }));

const { resendFailedSends, _resetResendBackoff, initOutboxResend } = await import(
  '@/core/outbox-resend'
);
initOutboxResend();

const CONV = 'conv-1';
const NO_PAGES = { older_cursor: null, has_older: false, newer_cursor: null, has_newer: false, total_count: 0 } as never;

function failed(id: string, createdAt: string, convId = CONV): void {
  addOutboxEntry({
    id,
    conversationId: convId,
    content: id,
    files: [],
    forceTools: [],
    anonymousMode: false,
    createdAt,
  });
  markOutboxFailed(convId, id);
}

function openConversation(id: string | null): void {
  useStore.setState({
    currentConversation: id ? ({ id, title: 't' } as never) : null,
  });
}

beforeEach(() => {
  localStorage.clear();
  _clearOutboxMemoryCache();
  sent.length = 0;
  stillFails.clear();
  _resetResendBackoff();
  vi.restoreAllMocks();
  useStore.getState().setMessages(CONV, [] as never, NO_PAGES);
  release = null;
  info.mockClear();
  openConversation(CONV);
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  vi.spyOn(useStore.getState(), 'getActiveRequest').mockReturnValue(null as never);
});

describe('resendFailedSends', () => {
  it('resends the open chat failed messages oldest first and says so', async () => {
    failed('m2', new Date(Date.now() - 1000).toISOString());
    failed('m1', new Date(Date.now() - 2000).toISOString());
    expect(await resendFailedSends('online')).toBe(2);
    expect(sent).toEqual(['m1', 'm2']);
    expect(info).toHaveBeenCalledWith('Resent 2 messages.');
  });

  it('skips other conversations and entries another live tab is sending', async () => {
    failed('mine', new Date(Date.now() - 2000).toISOString());
    failed('elsewhere', new Date(Date.now() - 2000).toISOString(), 'conv-2');
    failed('theirs', new Date(Date.now() - 1000).toISOString());
    const store = JSON.parse(localStorage.getItem(OUTBOX_STORAGE_KEY) || '{}');
    store[CONV][1].ownerTab = 'other-tab';
    localStorage.setItem(OUTBOX_STORAGE_KEY, JSON.stringify(store));
    localStorage.setItem(OUTBOX_TABS_STORAGE_KEY, JSON.stringify({ 'other-tab': Date.now() }));
    await resendFailedSends('online');
    expect(sent).toEqual(['mine']);
  });

  it('does nothing while the chat has a reply running', async () => {
    failed('m1', new Date(Date.now() - 2000).toISOString());
    vi.spyOn(useStore.getState(), 'getActiveRequest').mockReturnValue({} as never);
    expect(await resendFailedSends('online')).toBe(0);
    expect(sent).toEqual([]);
    expect(info).not.toHaveBeenCalled();
  });

  it('does nothing while offline', async () => {
    failed('m1', new Date(Date.now() - 2000).toISOString());
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    expect(await resendFailedSends('visible')).toBe(0);
  });

  it('a second trigger during a resend does not start another', async () => {
    failed('m1', new Date(Date.now() - 2000).toISOString());
    release = () => undefined; // the first send waits
    const first = resendFailedSends('online');
    expect(await resendFailedSends('visible')).toBe(0);
    release();
    await first;
    expect(sent).toEqual(['m1']);
  });

  it('leaves a failure older than a day to the user (a stale request)', async () => {
    const old = new Date(Date.now() - OUTBOX_RESEND_MAX_AGE_MS - 60_000).toISOString();
    failed('stale', old);
    failed('fresh', new Date().toISOString());
    await resendFailedSends('open');
    expect(sent).toEqual(['fresh']);
  });

  it('counts only sends that went through (review)', async () => {
    failed('ok', new Date(Date.now() - 2000).toISOString());
    failed('bad', new Date(Date.now() - 1000).toISOString());
    stillFails.add('bad');
    expect(await resendFailedSends('online')).toBe(1);
    expect(info).toHaveBeenCalledWith('Resent 1 message.');
  });

  it('backs off per message: an unreachable server is not hammered', async () => {
    failed('m1', new Date(Date.now() - 2000).toISOString());
    stillFails.add('m1');
    await resendFailedSends('visible');
    await resendFailedSends('visible'); // the next app switch, seconds later
    expect(sent).toEqual(['m1']);
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + OUTBOX_RESEND_BACKOFF_MS[0]! + 1000);
    await resendFailedSends('visible');
    expect(sent).toEqual(['m1', 'm1']);
  });

  it('gives up after the last backoff step', async () => {
    failed('m1', new Date(Date.now() - 2000).toISOString());
    stillFails.add('m1');
    let now = Date.now();
    for (let i = 0; i < OUTBOX_RESEND_BACKOFF_MS.length + 3; i++) {
      vi.spyOn(Date, 'now').mockReturnValue(now);
      await resendFailedSends('online');
      now += 60 * 60 * 1000;
    }
    expect(sent).toHaveLength(OUTBOX_RESEND_BACKOFF_MS.length + 1);
  });

  it('leaves a failure alone once a newer message exists (review: order)', async () => {
    failed('old', new Date(Date.now() - 5000).toISOString());
    useStore.getState().setMessages(
      CONV,
      [
        { id: 'old', role: 'user', content: 'old', created_at: new Date(Date.now() - 5000).toISOString() },
        { id: 'new', role: 'user', content: 'new', created_at: new Date(Date.now() - 1000).toISOString() },
      ] as never,
      NO_PAGES
    );
    expect(await resendFailedSends('online')).toBe(0);
    expect(sent).toEqual([]);
  });

  it('says nothing when nothing failed', async () => {
    expect(await resendFailedSends('open')).toBe(0);
    expect(info).not.toHaveBeenCalled();
  });
});

describe('triggers', () => {
  it('a trigger blocked by a running request checks again until it is done', async () => {
    vi.useFakeTimers();
    try {
      failed('m1', new Date(Date.now() - 2000).toISOString());
      const active = vi.spyOn(useStore.getState(), 'getActiveRequest');
      active.mockReturnValue({} as never); // a recovery poll still holds the chat
      window.dispatchEvent(new Event('online'));
      await vi.advanceTimersByTimeAsync(OUTBOX_RESEND_DELAY_MS * 3);
      expect(sent).toEqual([]);
      active.mockReturnValue(null as never);
      await vi.advanceTimersByTimeAsync(OUTBOX_RESEND_DELAY_MS * 2);
      expect(sent).toEqual(['m1']);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('failedEntries', () => {
  it('lists failed entries oldest first', () => {
    failed('b', new Date(Date.now() - 1000).toISOString());
    failed('a', new Date(Date.now() - 2000).toISOString());
    expect(failedEntries(CONV).map((e) => e.id)).toEqual(['a', 'b']);
  });
});
