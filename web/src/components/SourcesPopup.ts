import type { Source } from '../types/api';
import { createElement } from '../utils/dom';
import { SOURCES_ICON } from '../utils/icons';
import { safeHttpUrl } from '../utils/linkify';
import { createPopup, type PopupInstance } from './InfoPopup';

/**
 * One source row: a link only for an http(s) URL - a javascript: or data:
 * URL in the href would run when clicked - else the same row as plain text.
 */
function sourceItem(source: Source, index: number): HTMLElement {
  const href = safeHttpUrl(source.url);
  const inner = [
    createElement('span', { class: 'source-number' }, [String(index + 1)]),
    createElement('span', { class: 'source-title' }, [source.title]),
    createElement('span', { class: 'source-url' }, [href ? new URL(href).hostname : '']),
  ];
  return href
    ? createElement('a', { href, target: '_blank', rel: 'noopener noreferrer', class: 'source-item' }, inner)
    : createElement('div', { class: 'source-item' }, inner);
}

/**
 * The sources list
 */
function sourcesList(sources: Source[]): HTMLElement[] {
  return [
    createElement('div', { class: 'sources-header-badge' }, [
      createElement('span', { class: 'sources-count' }, [String(sources.length)]),
    ]),
    createElement('div', { class: 'sources-list' }, sources.map(sourceItem)),
  ];
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
  sourcesList
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
