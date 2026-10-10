/**
 * Unit tests for the send outbox: persistence of pending/failed sends
 * and reconciliation against server messages on conversation load.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  addOutboxEntry,
  getOutboxEntry,
  confirmOutboxEntry,
  markOutboxFailed,
  markOutboxPending,
  removeOutboxEntry,
  reconcileOutboxWithServer,
  _clearOutboxMemoryCache,
} from '@/core/outbox';
import { OUTBOX_STORAGE_KEY, OUTBOX_TAB_STALE_MS, OUTBOX_TABS_STORAGE_KEY } from '@/config';
import type { Message } from '@/types/api';

const CONV = 'conv-1';

function makeEntry(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    conversationId: CONV,
    content: `message ${id}`,
    files: [],
    forceTools: [],
    anonymousMode: false,
    createdAt: '2026-08-21T10:00:00.000Z',
    ...overrides,
  };
}

function serverMessage(id: string): Message {
  return {
    id,
    role: 'user',
    content: `message ${id}`,
    created_at: '2026-08-21T10:00:00.000Z',
  };
}

function readStored(): Record<string, unknown[]> {
  return JSON.parse(localStorage.getItem(OUTBOX_STORAGE_KEY) || '{}');
}

beforeEach(() => {
  localStorage.clear();
  _clearOutboxMemoryCache();
});

describe('outbox persistence', () => {
  it('persists an added entry to localStorage', () => {
    addOutboxEntry(makeEntry('m1'));
    const stored = readStored();
    expect(stored[CONV]).toHaveLength(1);
    expect((stored[CONV][0] as { id: string }).id).toBe('m1');
  });

  it('confirmOutboxEntry removes the entry', () => {
    addOutboxEntry(makeEntry('m1'));
    confirmOutboxEntry(CONV, 'm1');
    expect(readStored()[CONV] ?? []).toHaveLength(0);
    expect(getOutboxEntry(CONV, 'm1')).toBeUndefined();
  });

  it('markOutboxFailed flips status to failed', () => {
    addOutboxEntry(makeEntry('m1'));
    markOutboxFailed(CONV, 'm1');
    expect(getOutboxEntry(CONV, 'm1')?.status).toBe('failed');
    expect((readStored()[CONV][0] as { status: string }).status).toBe('failed');
  });

  it('removeOutboxEntry discards the entry', () => {
    addOutboxEntry(makeEntry('m1'));
    removeOutboxEntry(CONV, 'm1');
    expect(getOutboxEntry(CONV, 'm1')).toBeUndefined();
  });

  it('persists small files but strips blob preview URLs', () => {
    addOutboxEntry(
      makeEntry('m1', {
        files: [{ name: 'a.png', type: 'image/png', data: 'aGVsbG8=', previewUrl: 'blob:x' }],
      })
    );
    const stored = readStored()[CONV][0] as { files: { data: string; previewUrl?: string }[] };
    expect(stored.files[0].data).toBe('aGVsbG8=');
    expect(stored.files[0].previewUrl).toBeUndefined();
  });

  it('does not persist oversized files but keeps them in memory for retry', () => {
    const bigData = 'a'.repeat(3_000_000);
    addOutboxEntry(
      makeEntry('m1', { files: [{ name: 'big.png', type: 'image/png', data: bigData }] })
    );
    const stored = readStored()[CONV][0] as { files: unknown[]; filesDropped: boolean };
    expect(stored.files).toHaveLength(0);
    expect(stored.filesDropped).toBe(true);
    // Same-session retry still has the payload
    expect(getOutboxEntry(CONV, 'm1')?.files[0]?.data).toBe(bigData);
  });
});

describe('reconcileOutboxWithServer', () => {
  it('drops entries confirmed by the server from the outbox', () => {
    addOutboxEntry(makeEntry('m1'));
    const merged = reconcileOutboxWithServer(CONV, [serverMessage('m1')]);
    expect(merged).toHaveLength(1);
    expect(merged[0].status).toBeUndefined();
    expect(getOutboxEntry(CONV, 'm1')).toBeUndefined();
  });

  it('appends unconfirmed entries as failed messages', () => {
    addOutboxEntry(makeEntry('m2', { content: 'lost message' }));
    const merged = reconcileOutboxWithServer(CONV, [serverMessage('m1')]);
    expect(merged).toHaveLength(2);
    expect(merged[1].id).toBe('m2');
    expect(merged[1].status).toBe('failed');
    expect(merged[1].content).toBe('lost message');
    expect(getOutboxEntry(CONV, 'm2')?.status).toBe('failed');
  });

  it('keeps in-flight entries pending instead of failing them', () => {
    addOutboxEntry(makeEntry('m3'));
    markOutboxPending(CONV, 'm3');
    const merged = reconcileOutboxWithServer(CONV, []);
    expect(merged).toHaveLength(1);
    expect(merged[0].status).toBe('pending');
    expect(getOutboxEntry(CONV, 'm3')?.status).toBe('pending');
  });

  it('does not touch entries of other conversations', () => {
    addOutboxEntry(makeEntry('m1', { conversationId: 'other-conv' }));
    const merged = reconcileOutboxWithServer(CONV, []);
    expect(merged).toHaveLength(0);
    expect(getOutboxEntry('other-conv', 'm1')).toBeDefined();
  });
});

describe('outbox shared by two tabs', () => {
  /** An entry another tab of this browser is sending (heartbeat at `seenAt`). */
  function storeForeignEntry(id: string, seenAt: number | null): void {
    const entry = { ...makeEntry(id), filesDropped: false, status: 'pending', ownerTab: 'tab-b' };
    localStorage.setItem(OUTBOX_STORAGE_KEY, JSON.stringify({ [CONV]: [entry] }));
    if (seenAt !== null) localStorage.setItem(OUTBOX_TABS_STORAGE_KEY, JSON.stringify({ 'tab-b': seenAt }));
  }

  it("leaves a live tab's in-flight send alone (not failed, not rendered here)", () => {
    storeForeignEntry('m1', Date.now());
    const merged = reconcileOutboxWithServer(CONV, []);
    expect(merged).toHaveLength(0);
    expect(getOutboxEntry(CONV, 'm1')?.status).toBe('pending');
  });

  it("fails a send whose tab stopped beating (closed or crashed)", () => {
    storeForeignEntry('m1', Date.now() - OUTBOX_TAB_STALE_MS - 1_000);
    const merged = reconcileOutboxWithServer(CONV, []);
    expect(merged.map((m) => m.status)).toEqual(['failed']);
    expect(getOutboxEntry(CONV, 'm1')?.status).toBe('failed');
  });

  it('fails a send whose tab never beat', () => {
    storeForeignEntry('m1', null);
    expect(reconcileOutboxWithServer(CONV, []).map((m) => m.status)).toEqual(['failed']);
  });

  it('a live in-flight send keeps this tab beating', () => {
    addOutboxEntry(makeEntry('m1'));
    markOutboxPending(CONV, 'm1');
    const owner = (readStored()[CONV][0] as { ownerTab?: string }).ownerTab;
    const tabs = JSON.parse(localStorage.getItem(OUTBOX_TABS_STORAGE_KEY) || '{}') as Record<string, number>;
    expect(owner).toBeTruthy();
    expect(Date.now() - (tabs[owner as string] ?? 0)).toBeLessThan(OUTBOX_TAB_STALE_MS);
  });

  it('a retry from this tab takes over a dead tab\'s send', () => {
    storeForeignEntry('m1', null);
    markOutboxPending(CONV, 'm1');
    expect((readStored()[CONV][0] as { ownerTab?: string }).ownerTab).not.toBe('tab-b');
    expect(reconcileOutboxWithServer(CONV, []).map((m) => m.status)).toEqual(['pending']);
  });
});
