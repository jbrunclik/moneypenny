/**
 * Data page, Documents section (document memory): rows show what a saved
 * document holds and when it is used, download/delete/restore call through,
 * an empty library explains how documents get there, and a document past its
 * last day reads as expired.
 */
import { describe, it, expect, vi } from 'vitest';
import { renderKVStorePage, type KVStoreCallbacks } from '@/components/KVStorePage';
import type { DocumentsResponse, SavedDocument } from '@/types/api';

vi.mock('@/components/Modal', () => ({ showConfirm: vi.fn(() => Promise.resolve(true)) }));

function doc(id: string, extra: Partial<SavedDocument> = {}): SavedDocument {
  return {
    id,
    title: `<b>${id}</b>`,
    summary: 'Equity value per exit valuation',
    use_for: 'Exit scenarios',
    filename: 'waterfall.pdf',
    mime_type: 'application/pdf',
    size_bytes: 1_250_000,
    created_at: '2026-11-20T10:00:00Z',
    valid_until: null,
    deleted_at: null,
    last_opened_at: null,
    source_conversation_id: null,
    ...extra,
  };
}

function data(documents: SavedDocument[], deleted: SavedDocument[] = []): DocumentsResponse {
  return { documents, deleted, limit: 50, bytes_used: 0, bytes_limit: 200 };
}

function callbacks(): KVStoreCallbacks {
  return {
    onRefresh: vi.fn(),
    onNamespaceExpand: vi.fn() as KVStoreCallbacks['onNamespaceExpand'],
    onDeleteKey: vi.fn(() => Promise.resolve()),
    onClearNamespace: vi.fn(() => Promise.resolve()),
    onDeleteMemory: vi.fn(() => Promise.resolve()),
    onSetMemoryProtected: vi.fn(() => Promise.resolve()),
    onRestoreMemory: vi.fn(() => Promise.resolve()),
    onRestorePreviousMemory: vi.fn() as KVStoreCallbacks['onRestorePreviousMemory'],
    onDeleteDocument: vi.fn(() => Promise.resolve()),
    onRestoreDocument: vi.fn(() => Promise.resolve()),
    onDownloadDocument: vi.fn(),
  };
}

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

function page(docs: DocumentsResponse, cb = callbacks()): HTMLDivElement {
  return renderKVStorePage({ namespaces: [] }, [], cb, { documents: docs });
}

describe('Data page documents', () => {
  it('shows title, file, summary and use-for as text', () => {
    const el = page(data([doc('d1', { valid_until: '2099-06-30' })]));
    const row = el.querySelector('.kv-doc-item')!;
    expect(row.querySelector('.kv-doc-title')?.textContent).toBe('<b>d1</b>');
    expect(row.querySelector('b')).toBeNull();
    expect(row.querySelector('.kv-doc-file')?.textContent).toBe('waterfall.pdf · 1.2 MB');
    expect(row.querySelector('.kv-doc-summary')?.textContent).toBe('Equity value per exit valuation');
    expect(row.querySelector('.kv-doc-use-for')?.textContent).toBe('Use for: Exit scenarios');
    expect(row.querySelector('.memory-until-badge')?.textContent).toMatch(/^Until /);
    expect(el.querySelector('.kv-doc-section .kv-store-section-count')?.textContent).toBe('1/50');
  });

  it('marks a document past its last day as expired', () => {
    const el = page(data([doc('d1', { valid_until: '2020-01-01' })]));
    expect(el.querySelector('.kv-doc-item .memory-until-badge')?.textContent).toMatch(/^Expired /);
  });

  it('explains an empty library', () => {
    const el = page(data([]));
    expect(el.querySelector('.kv-doc-section')?.textContent).toContain('No documents yet');
    expect(el.querySelector('.kv-doc-section')?.textContent).toContain(
      'Ask Moneypenny to keep a document you share in a chat.'
    );
  });

  it('downloads and deletes through the callbacks', async () => {
    const cb = callbacks();
    const el = page(data([doc('d1')]), cb);
    el.querySelector<HTMLButtonElement>('.kv-doc-download')!.click();
    expect(cb.onDownloadDocument).toHaveBeenCalledWith('d1', 'waterfall.pdf');

    el.querySelector<HTMLButtonElement>('.kv-doc-delete')!.click();
    await flush();
    expect(cb.onDeleteDocument).toHaveBeenCalledWith('d1');
    expect(el.querySelector('.kv-doc-item')).toBeNull();
  });

  it('restores a recently deleted document', async () => {
    const cb = callbacks();
    const el = page(data([], [doc('d2', { deleted_at: '2026-11-23T10:00:00Z' })]), cb);
    const deleted = el.querySelector('.kv-doc-deleted')!;
    expect(deleted.querySelector('.kv-doc-title')?.textContent).toBe('<b>d2</b>');
    deleted.querySelector<HTMLButtonElement>('.kv-doc-restore')!.click();
    await flush();
    expect(cb.onRestoreDocument).toHaveBeenCalledWith('d2');
    expect(el.querySelector('.kv-doc-deleted')).toBeNull();
  });

  it('leaves the section out when documents could not be loaded', () => {
    const el = renderKVStorePage({ namespaces: [] }, [], callbacks());
    expect(el.querySelector('.kv-doc-section')).toBeNull();
  });
});
