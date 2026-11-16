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
  _clearOutboxMemoryCache,
} from '@/core/outbox';
import { OUTBOX_RESEND_MAX_AGE_MS, OUTBOX_STORAGE_KEY, OUTBOX_TABS_STORAGE_KEY } from '@/config';
import { useStore } from '@/state/store';

const sent: string[] = [];
let release: (() => void) | null = null;

vi.mock('@/core/rerun', () => ({
  resendOutboxEntry: vi.fn(async (_convId: string, id: string) => {
    sent.push(id);
    if (release === null) return;
    await new Promise<void>((resolve) => {
      release = resolve;
    });
  }),
}));

const info = vi.fn();
vi.mock('@/components/Toast', () => ({ toast: { info: (m: string) => info(m) } }));

const { resendFailedSends } = await import('@/core/outbox-resend');

const CONV = 'conv-1';

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

  it('says nothing when nothing failed', async () => {
    expect(await resendFailedSends('open')).toBe(0);
    expect(info).not.toHaveBeenCalled();
  });
});

describe('failedEntries', () => {
  it('lists failed entries oldest first', () => {
    failed('b', new Date(Date.now() - 1000).toISOString());
    failed('a', new Date(Date.now() - 2000).toISOString());
    expect(failedEntries(CONV).map((e) => e.id)).toEqual(['a', 'b']);
  });
});
