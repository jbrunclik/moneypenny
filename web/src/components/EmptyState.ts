/**
 * The one empty state used across feature pages (Planner, Sports, Language,
 * Command Center, Data): a tinted icon, a title, a muted hint and an
 * optional call to action. Styles: components/empty-state.css.
 */
import { createElement } from '../utils/dom';
import { createIconElement, type IconHtml } from '../utils/icons';

export interface EmptyStateElementOptions {
  icon: IconHtml;
  title: string;
  hint?: string;
  /** The one action the empty page offers */
  cta?: HTMLElement;
  /** 'success' tints the icon green (e.g. the planner's "all clear") */
  variant?: 'success';
  /** Tighter spacing for an empty section inside a page */
  compact?: boolean;
  /** Extra class names (hooks for the page's own code and tests) */
  className?: string;
}

function emptyStateClasses(options: Pick<EmptyStateElementOptions, 'variant' | 'compact' | 'className'>): string {
  return [
    'empty-state',
    options.variant ? `empty-state--${options.variant}` : '',
    options.compact ? 'empty-state--compact' : '',
    options.className ?? '',
  ].filter(Boolean).join(' ');
}

/** The empty state as an element. */
export function createEmptyState(options: EmptyStateElementOptions): HTMLDivElement {
  const el = createElement('div', { class: emptyStateClasses(options) });
  el.appendChild(createIconElement('empty-state__icon', options.icon, 'div'));
  el.appendChild(createElement('p', { class: 'empty-state__title' }, [options.title]));
  if (options.hint) el.appendChild(createElement('p', { class: 'empty-state__hint' }, [options.hint]));
  if (options.cta) el.appendChild(options.cta);
  return el;
}
