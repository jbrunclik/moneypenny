/**
 * The one empty state used across feature pages (Planner, Sports, Language,
 * Command Center, Data): a tinted icon, a title, a muted hint and an
 * optional call to action. Styles: components/empty-state.css.
 */
import { escapeHtml } from '../utils/dom';

export interface EmptyStateOptions {
  /** SVG icon markup (trusted - from utils/icons) */
  icon: string;
  title: string;
  hint?: string;
  /** Trusted button markup for the one action the empty page offers */
  ctaHtml?: string;
  /** 'success' tints the icon green (e.g. the planner's "all clear") */
  variant?: 'success';
  /** Tighter spacing for an empty section inside a page */
  compact?: boolean;
  /** Extra class names (hooks for the page's own code and tests) */
  className?: string;
}

export function renderEmptyStateHtml(options: EmptyStateOptions): string {
  const classes = [
    'empty-state',
    options.variant ? `empty-state--${options.variant}` : '',
    options.compact ? 'empty-state--compact' : '',
    options.className ?? '',
  ].filter(Boolean).join(' ');
  const icon = options.icon ? `<div class="empty-state__icon">${options.icon}</div>` : '';
  const hint = options.hint ? `<p class="empty-state__hint">${escapeHtml(options.hint)}</p>` : '';
  return `
    <div class="${classes}">
      ${icon}
      <p class="empty-state__title">${escapeHtml(options.title)}</p>
      ${hint}
      ${options.ctaHtml ?? ''}
    </div>
  `;
}
