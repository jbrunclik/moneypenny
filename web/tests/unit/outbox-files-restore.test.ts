/**
 * Unsent attachments survive a reload in IndexedDB (outbox-files.ts); the
 * localStorage outbox only keeps files under OUTBOX_PERSIST_MAX_FILE_CHARS.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const idb = new Map<string, unknown>();
vi.mock('@/core/outbox-files', () => ({
  saveOutboxFiles: vi.fn(async (id: string, files: unknown) => void idb.set(id, files)),
  loadOutboxFiles: vi.fn(async (id: string) => idb.get(id) ?? null),
  deleteOutboxFiles: vi.fn(async (id: string) => void idb.delete(id)),
}));

import {
  _clearOutboxMemoryCache,
  addOutboxEntry,
  confirmOutboxEntry,
  removeOutboxEntry,
  restoreOutboxEntry,
} from '@/core/outbox';
import { deleteOutboxFiles, saveOutboxFiles } from '@/core/outbox-files';

const BIG = { name: 'big.pdf', type: 'application/pdf', data: 'x'.repeat(2_500_000), previewUrl: 'blob:p' };

function add(id: string, files = [BIG]): void {
  addOutboxEntry({
    id,
    conversationId: 'c1',
    content: 'hello',
    files,
    forceTools: [],
    anonymousMode: false,
    createdAt: '2026-10-03T10:00:00Z',
  });
}

describe('outbox attachments across a reload', () => {
  beforeEach(() => {
    localStorage.clear();
    idb.clear();
    _clearOutboxMemoryCache();
    vi.clearAllMocks();
  });

  it('a retry after a reload gets the attachments back from IndexedDB', async () => {
    add('m1');
    await Promise.resolve();
    _clearOutboxMemoryCache(); // the page reloaded: in-memory files are gone

    const entry = await restoreOutboxEntry('c1', 'm1');

    expect(entry?.filesDropped).toBe(false);
    expect(entry?.files).toEqual([expect.objectContaining({ name: 'big.pdf', type: 'application/pdf', data: BIG.data })]);
  });

  it('nothing to restore leaves the entry marked as dropped', async () => {
    add('m1');
    idb.clear();
    _clearOutboxMemoryCache();

    const entry = await restoreOutboxEntry('c1', 'm1');

    expect(entry?.filesDropped).toBe(true);
    expect(entry?.files).toEqual([]);
  });

  it('confirming or discarding a send deletes its stored attachments', () => {
    add('m1');
    add('m2');

    confirmOutboxEntry('c1', 'm1');
    removeOutboxEntry('c1', 'm2');

    expect(deleteOutboxFiles).toHaveBeenCalledWith('m1');
    expect(deleteOutboxFiles).toHaveBeenCalledWith('m2');
  });

  it('a text-only message never touches IndexedDB', () => {
    add('m1', []);
    confirmOutboxEntry('c1', 'm1');

    expect(saveOutboxFiles).not.toHaveBeenCalled();
    expect(deleteOutboxFiles).not.toHaveBeenCalled();
  });
});
