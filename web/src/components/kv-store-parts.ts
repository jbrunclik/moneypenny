/**
 * Pieces the Data page's sections share (memories, documents): section
 * headings and the dates rows show.
 */
import { BYTES_PER_KB, BYTES_PER_MB } from '../constants';
import { createElement } from '../utils/dom';
import { createIconElement, type IconHtml } from '../utils/icons';

/** A section heading: icon, title and its count. */
export function sectionTitle(icon: IconHtml, title: string, count: string): HTMLHeadingElement {
  return createElement('h3', { class: 'kv-store-section-title' }, [
    createIconElement('section-icon', icon),
    ` ${title} `,
    createElement('span', { class: 'kv-store-section-count' }, [count]),
  ]);
}

/**
 * Format relative time (e.g., "2 days ago")
 */
export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);
  const diffWeeks = Math.floor(diffDays / 7);
  const diffMonths = Math.floor(diffDays / 30);

  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffWeeks < 4) return `${diffWeeks}w ago`;
  return `${diffMonths}mo ago`;
}

/**
 * A memory's or document's last day ("YYYY-MM-DD", a calendar date) as "Fri 21 Nov".
 * Parsed as local noon so no timezone shifts it to the day before.
 */
export function formatUntil(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

/** A file size as "840 KB" or "1.2 MB". */
export function formatFileSize(bytes: number): string {
  if (bytes < BYTES_PER_MB) return `${Math.max(1, Math.round(bytes / BYTES_PER_KB))} KB`;
  return `${(bytes / BYTES_PER_MB).toFixed(1)} MB`;
}
