import type { Source } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { SOURCES_ICON } from '../utils/icons';
import { safeHttpUrl } from '../utils/linkify';
import { createPopup, type PopupInstance } from './InfoPopup';

/**
 * One source row: a link only for an http(s) URL - escaping keeps a
 * javascript: or data: URL inside the attribute, but a click would still run
 * it - else the same row as plain text.
 */
function renderSourceItem(source: Source, index: number): string {
  const href = safeHttpUrl(source.url);
  const inner = `
        <span class="source-number">${index + 1}</span>
        <span class="source-title">${escapeHtml(source.title)}</span>
        <span class="source-url">${href ? escapeHtml(new URL(href).hostname) : ''}</span>`;
  return href
    ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" class="source-item">${inner}</a>`
    : `<div class="source-item">${inner}</div>`;
}

/**
 * Render sources list HTML
 */
function renderSourcesList(sources: Source[]): string {
  const sourcesHtml = sources.map((source, index) => renderSourceItem(source, index)).join('');

  return `
    <div class="sources-header-badge">
      <span class="sources-count">${sources.length}</span>
    </div>
    <div class="sources-list">
      ${sourcesHtml}
    </div>
  `;
}

// Create the sources popup instance
const sourcesPopup: PopupInstance<Source[]> = createPopup<Source[]>(
  {
    id: 'sources-popup',
    eventName: 'sources:open',
    icon: SOURCES_ICON,
    title: 'Sources',
    styleClass: 'sources',
  },
  renderSourcesList
);

/**
 * Initialize sources popup event handlers
 */
export function initSourcesPopup(): void {
  sourcesPopup.init();
}

/**
 * Open sources popup with the given sources
 */
export function openSourcesPopup(sources: Source[]): void {
  if (sources && sources.length > 0) {
    sourcesPopup.open(sources);
  }
}

/**
 * Close sources popup
 */
export function closeSourcesPopup(): void {
  sourcesPopup.close();
}