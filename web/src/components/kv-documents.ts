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

function setCount(section: HTMLElement, list: HTMLElement, limit?: number): void {
  const countEl = section.querySelector('.kv-store-section-count');
  if (countEl) countEl.textContent = limit ? `${list.children.length}/${limit}` : String(list.children.length);
}

function renderDocumentItem(
  doc: SavedDocument,
  onRemoved: () => void,
  callbacks: DocumentCallbacks
): HTMLDivElement {
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
    callbacks.onDownloadDocument(doc.id, doc.filename);
  });
  const remove = async (): Promise<void> => {
    const confirmed = await showConfirm({
      message: `Delete “${doc.title}”? It stays in Recently deleted for a while.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!confirmed) return;
    try {
      await callbacks.onDeleteDocument(doc.id);
      item.remove();
      onRemoved();
    } catch {
      // Error surfaced by the caller
    }
  };
  item.querySelector('.kv-doc-delete')?.addEventListener('click', () => {
    void remove();
  });
  return item;
}

function renderLiveSection(data: DocumentsResponse, callbacks: DocumentCallbacks): HTMLDivElement {
  const section = createElement('div', { class: 'kv-store-section kv-doc-section' }, [
    sectionTitle(FILE_ICON, 'Documents', `${data.documents.length}/${data.limit}`),
  ]);
  const empty = (): HTMLDivElement =>
    createEmptyState({
      icon: FILE_ICON,
      title: 'No documents yet',
      hint: 'Ask Moneypenny to keep a document you share in a chat.',
      compact: true,
    });
  if (data.documents.length === 0) {
    section.appendChild(empty());
    return section;
  }
  const list = createElement('div', { class: 'kv-memories-list' });
  const onRemoved = (): void => {
    setCount(section, list, data.limit);
    if (list.children.length === 0) list.replaceWith(empty());
  };
  for (const doc of data.documents) list.appendChild(renderDocumentItem(doc, onRemoved, callbacks));
  section.appendChild(list);
  return section;
}

function renderDeletedSection(deleted: SavedDocument[], callbacks: DocumentCallbacks): HTMLDivElement {
  const list = createElement('div', { class: 'kv-memories-list' });
  const section = createElement('div', { class: 'kv-store-section kv-doc-deleted-section' }, [
    sectionTitle(RESTORE_ICON, 'Recently deleted documents', String(deleted.length)),
    list,
  ]);
  for (const doc of deleted) {
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
        await callbacks.onRestoreDocument(doc.id);
        item.remove();
        setCount(section, list);
        if (list.children.length === 0) section.remove();
      } catch {
        // Error surfaced by the caller
      }
    };
    item.querySelector('.kv-doc-restore')?.addEventListener('click', () => {
      void restore();
    });
    list.appendChild(item);
  }
  return section;
}

/** The Documents section, plus Recently deleted documents when there are any. */
export function renderDocumentsSections(data: DocumentsResponse, callbacks: DocumentCallbacks): HTMLDivElement[] {
  const sections = [renderLiveSection(data, callbacks)];
  if (data.deleted.length > 0) sections.push(renderDeletedSection(data.deleted, callbacks));
  return sections;
}
