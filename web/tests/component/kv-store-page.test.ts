/**
 * Data page (memories + key-value storage): rows show their text as text,
 * protect re-renders the row, restore removes it, and an expanded namespace
 * lists its keys with the JSON value pretty-printed and colored by token.
 */
import { describe, it, expect, vi } from 'vitest';
import { renderKVStorePage, type KVStoreCallbacks } from '@/components/KVStorePage';
import type { Memory } from '@/types/api';

function memory(id: string, extra: Partial<Memory> = {}): Memory {
  return { id, content: `<b>${id}</b>`, category: null, created_at: '', updated_at: new Date().toISOString(), ...extra } as Memory;
}

function callbacks(): KVStoreCallbacks {
  return {
    onRefresh: vi.fn(),
    onNamespaceExpand: vi.fn(() =>
      Promise.resolve({
        namespace: 'ns',
        keys: [
          { key: 'k', value: '{"name":"Eva 2","age":7,"ok":true}' },
          { key: 'raw', value: 'not <json>' },
        ],
      })
    ) as KVStoreCallbacks['onNamespaceExpand'],
    onDeleteKey: vi.fn(() => Promise.resolve()),
    onClearNamespace: vi.fn(() => Promise.resolve()),
    onRestoreProject: vi.fn(() => Promise.resolve()),
    onDeleteMemory: vi.fn(() => Promise.resolve()),
    onSetMemoryProtected: vi.fn(() => Promise.resolve()),
    onRestoreMemory: vi.fn(() => Promise.resolve()),
    onRestorePreviousMemory: vi.fn((id: string) =>
      Promise.resolve(memory(id, { content: 'Has a dog named Max', previous_content: 'Has a dog' }))
    ),
    onDeleteDocument: vi.fn(() => Promise.resolve()),
    onRestoreDocument: vi.fn(() => Promise.resolve()),
    onDownloadDocument: vi.fn(),
  };
}

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('KVStorePage', () => {
  it('shows memory text as text and re-renders a row when protected', async () => {
    const cb = callbacks();
    const page = renderKVStorePage({ namespaces: [] }, [memory('m1', { category: 'fact' })], cb);
    const row = page.querySelector('.memory-item')!;
    expect(row.querySelector('.memory-text')?.textContent).toBe('<b>m1</b>');
    expect(row.querySelector('b')).toBeNull();
    expect(row.querySelector('.memory-category--fact')?.textContent).toBe('Fact');

    row.querySelector<HTMLButtonElement>('.memory-protect')!.click();
    await flush();
    expect(cb.onSetMemoryProtected).toHaveBeenCalledWith('m1', true);
    expect(row.classList.contains('memory-item--protected')).toBe(true);
    expect(row.querySelector('.memory-protect')?.getAttribute('aria-pressed')).toBe('true');
    expect(row.querySelector('.memory-protected-badge')).not.toBeNull();
  });

  it('shows a last day and restores the version before the last change', async () => {
    const cb = callbacks();
    const page = renderKVStorePage(
      { namespaces: [] },
      [memory('m1', { content: 'Has a dog', previous_content: 'Has a dog named Max', valid_until: '2026-11-21' })],
      cb
    );
    const row = page.querySelector('.memory-item')!;
    expect(row.querySelector('.memory-until-badge')?.textContent).toMatch(/^Until .*21/);
    expect(row.querySelector('.memory-previous')).toBeNull();

    row.querySelector<HTMLButtonElement>('.memory-history')!.click();
    expect(row.querySelector('.memory-previous-text')?.textContent).toBe('Has a dog named Max');

    row.querySelector<HTMLButtonElement>('.memory-restore-previous')!.click();
    await flush();
    expect(cb.onRestorePreviousMemory).toHaveBeenCalledWith('m1');
    expect(row.querySelector('.memory-text')?.textContent).toBe('Has a dog named Max');
    expect(row.querySelector('.memory-previous')).toBeNull();
    expect(row.querySelector('.memory-history')).not.toBeNull();
  });

  it('offers no history for a memory that never changed', () => {
    const page = renderKVStorePage({ namespaces: [] }, [memory('m1')], callbacks());
    expect(page.querySelector('.memory-history')).toBeNull();
    expect(page.querySelector('.memory-until-badge')).toBeNull();
  });

  it('restores a deleted memory and drops the empty section', async () => {
    const cb = callbacks();
    const page = renderKVStorePage({ namespaces: [] }, [], cb, {
      deletedMemories: [memory('d1', { deleted_at: new Date().toISOString() })],
    });
    expect(page.querySelector('.memory-item--deleted .memory-time')?.textContent).toBe('deleted just now');
    page.querySelector<HTMLButtonElement>('.memory-restore')!.click();
    await flush();
    expect(cb.onRestoreMemory).toHaveBeenCalledWith('d1');
    expect(page.querySelector('.memory-item--deleted')).toBeNull();
  });

  it('lists a namespace with highlighted JSON values', async () => {
    const page = renderKVStorePage({ namespaces: [{ namespace: 'ns', key_count: 2 }] }, [], callbacks());
    page.querySelector<HTMLElement>('.kv-namespace-title-row')!.click();
    await flush();
    const [json, raw] = [...page.querySelectorAll<HTMLElement>('.kv-key-value')];
    expect(json?.textContent).toBe('{\n  "name": "Eva 2",\n  "age": 7,\n  "ok": true\n}');
    expect([...json!.querySelectorAll('.json-string')].map((s) => s.textContent)).toEqual([
      '"name"',
      '"Eva 2"',
      '"age"',
      '"ok"',
    ]);
    expect([...json!.querySelectorAll('.json-number')].map((s) => s.textContent)).toEqual(['2', '7']);
    expect(json?.querySelector('.json-keyword')?.textContent).toBe('true');
    expect(raw?.textContent).toBe('not <json>');
    expect(raw?.children).toHaveLength(0);
  });
});

describe('recently deleted projects', () => {
  it('lists them with Restore and drops a restored one', async () => {
    const cb = callbacks();
    const page = renderKVStorePage({ namespaces: [] }, [], cb, {
      deletedProjects: [
        {
          id: 'p1',
          name: 'Old client',
          owner_id: 'u',
          is_owner: true,
          shared: false,
          member_names: [],
          member_ids: ['u'],
          chat_count: 0,
          unread_count: 0,
          created_at: '2026-11-01T00:00:00Z',
          updated_at: '2026-11-01T00:00:00Z',
          deleted_at: '2026-11-20T00:00:00Z',
        },
      ],
    });
    expect(page.querySelector('.kv-deleted-projects')?.textContent).toContain('Old client');

    page.querySelector<HTMLButtonElement>('.kv-deleted-projects .kv-project-restore')?.click();

    await vi.waitFor(() => expect(cb.onRestoreProject).toHaveBeenCalledWith('p1'));
    await vi.waitFor(() => expect(page.querySelector('.kv-deleted-projects')).toBeNull());
  });
});
