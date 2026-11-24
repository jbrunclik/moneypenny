/**
 * Data page, Documents section (document memory): the documents the
 * assistant keeps, what each holds and when it is used, with download and
 * delete, and the recently deleted ones with restore.
 */
import { createElement } from '../utils/dom';
import { createEmptyState } from './EmptyState';
import { createIconButton, DELETE_ICON, DOWNLOAD_ICON, FILE_ICON, RESTORE_ICON } from '../utils/icons';
import type { DocumentsResponse, SavedDocument } from '../types/api';
import { showConfirm } from './Modal';
import { formatFileSize, formatRelativeTime, formatUntil, sectionTitle } from './kv-store-parts';

/** The Documents section's actions (errors are surfaced by the caller). */
export interface DocumentCallbacks {
  onDeleteDocument: (documentId: string) => Promise<void>;
  onRestoreDocument: (documentId: string) => Promise<void>;
  onDownloadDocument: (documentId: string, fileName: string) => void;
}

/** Today as "YYYY-MM-DD" in local time (end dates are local calendar days). */
function localToday(): string {
  const now = new Date();
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** The title, file line, summary and use-for every document row shows. */
function documentBody(doc: SavedDocument): HTMLElement[] {
  return [
    createElement('span', { class: 'kv-doc-title' }, [doc.title]),
    createElement('div', { class: 'kv-doc-file' }, [`${doc.filename} · ${formatFileSize(doc.size_bytes)}`]),
    createElement('div', { class: 'kv-doc-summary' }, [doc.summary]),
    createElement('div', { class: 'kv-doc-use-for' }, [`Use for: ${doc.use_for}`]),
  ];
}

function endDateBadge(validUntil: string): HTMLSpanElement {
  const expired = validUntil < localToday();
  return createElement(
    'span',
    { class: 'memory-until-badge', title: expired ? 'Past its last day' : 'Cleared away after this day' },
    [`${expired ? 'Expired' : 'Until'} ${formatUntil(validUntil)}`]
  );
}

/** The two lists, kept in step: a delete moves a row to Recently deleted, a restore back. */
interface DocumentLists {
  liveSection: HTMLDivElement;
  liveList: HTMLDivElement;
  deletedSection: HTMLDivElement;
  deletedList: HTMLDivElement;
  limit: number;
  callbacks: DocumentCallbacks;
}

function emptyLibrary(): HTMLDivElement {
  return createEmptyState({
    icon: FILE_ICON,
    title: 'No documents yet',
    hint: 'Ask Moneypenny to keep a document you share in a chat.',
    compact: true,
  });
}

/** Counts, the empty state and the deleted section's visibility, after a move. */
function syncLists(lists: DocumentLists): void {
  const liveCount = lists.liveSection.querySelector('.kv-store-section-count');
  if (liveCount) liveCount.textContent = `${lists.liveList.children.length}/${lists.limit}`;
  const deletedCount = lists.deletedSection.querySelector('.kv-store-section-count');
  if (deletedCount) deletedCount.textContent = String(lists.deletedList.children.length);
  lists.liveSection.querySelector('.empty-state')?.remove();
  if (lists.liveList.children.length === 0) lists.liveSection.appendChild(emptyLibrary());
  lists.deletedSection.hidden = lists.deletedList.children.length === 0;
}

function renderLiveItem(doc: SavedDocument, lists: DocumentLists): HTMLDivElement {
  const item = createElement('div', { class: 'memory-item kv-doc-item' }, [
    createElement('div', { class: 'memory-content-row' }, [
      createElement('div', { class: 'kv-doc-body' }, documentBody(doc)),
      createIconButton({ class: 'kv-doc-download', title: 'Download' }, DOWNLOAD_ICON),
      createIconButton({ class: 'kv-doc-delete', title: 'Delete document' }, DELETE_ICON),
    ]),
    createElement('div', { class: 'memory-meta' }, [
      doc.valid_until && endDateBadge(doc.valid_until),
      createElement('span', { class: 'memory-time' }, [`saved ${formatRelativeTime(doc.created_at)}`]),
    ]),
  ]);
  item.querySelector('.kv-doc-download')?.addEventListener('click', () => {
    lists.callbacks.onDownloadDocument(doc.id, doc.filename);
  });
  const remove = async (): Promise<void> => {
    const confirmed = await showConfirm({
      message: `Delete “${doc.title}”? It stays in Recently deleted for a while.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!confirmed) return;
    try {
      await lists.callbacks.onDeleteDocument(doc.id);
    } catch {
      return; // Error surfaced by the caller; the row stays
    }
    item.remove();
    lists.deletedList.prepend(renderDeletedItem({ ...doc, deleted_at: new Date().toISOString() }, lists));
    syncLists(lists);
  };
  item.querySelector('.kv-doc-delete')?.addEventListener('click', () => {
    void remove();
  });
  return item;
}

function renderDeletedItem(doc: SavedDocument, lists: DocumentLists): HTMLDivElement {
  const item = createElement('div', { class: 'memory-item memory-item--deleted kv-doc-deleted' }, [
    createElement('div', { class: 'memory-content-row' }, [
      createElement('div', { class: 'kv-doc-body' }, [createElement('span', { class: 'kv-doc-title' }, [doc.title])]),
      createIconButton({ class: 'kv-doc-restore', title: 'Restore this document' }, RESTORE_ICON),
    ]),
    createElement('div', { class: 'memory-meta' }, [
      createElement('span', { class: 'memory-time' }, [
        `deleted ${doc.deleted_at ? formatRelativeTime(doc.deleted_at) : ''}`,
      ]),
    ]),
  ]);
  const restore = async (): Promise<void> => {
    try {
      await lists.callbacks.onRestoreDocument(doc.id);
    } catch {
      return; // Error surfaced by the caller (e.g. the library is full)
    }
    item.remove();
    // A past end date is dropped on restore (the server does the same)
    const today = localToday();
    const validUntil = doc.valid_until && doc.valid_until < today ? null : doc.valid_until;
    lists.liveList.prepend(renderLiveItem({ ...doc, deleted_at: null, valid_until: validUntil }, lists));
    syncLists(lists);
  };
  item.querySelector('.kv-doc-restore')?.addEventListener('click', () => {
    void restore();
  });
  return item;
}

/** The Documents section, plus Recently deleted documents (hidden while empty). */
export function renderDocumentsSections(data: DocumentsResponse, callbacks: DocumentCallbacks): HTMLDivElement[] {
  const liveList = createElement('div', { class: 'kv-memories-list' });
  const deletedList = createElement('div', { class: 'kv-memories-list' });
  const lists: DocumentLists = {
    liveSection: createElement('div', { class: 'kv-store-section kv-doc-section' }, [
      sectionTitle(FILE_ICON, 'Documents', ''),
      liveList,
    ]),
    liveList,
    deletedSection: createElement('div', { class: 'kv-store-section kv-doc-deleted-section' }, [
      sectionTitle(RESTORE_ICON, 'Recently deleted documents', ''),
      deletedList,
    ]),
    deletedList,
    limit: data.limit,
    callbacks,
  };
  for (const doc of data.documents) liveList.appendChild(renderLiveItem(doc, lists));
  for (const doc of data.deleted) deletedList.appendChild(renderDeletedItem(doc, lists));
  syncLists(lists);
  return [lists.liveSection, lists.deletedSection];
}
