/**
 * One empty-state component across the feature pages.
 */
import { describe, it, expect } from 'vitest';
import { renderEmptyStateHtml } from '@/components/EmptyState';

function render(html: string): HTMLElement {
  const el = document.createElement('div');
  el.innerHTML = html;
  return el.firstElementChild as HTMLElement;
}

describe('renderEmptyStateHtml', () => {
  it('renders icon, title, hint and an optional call to action', () => {
    const el = render(
      renderEmptyStateHtml({ icon: '<svg></svg>', title: 'No agents yet', hint: 'Create one.', ctaHtml: '<button>Go</button>' })
    );
    expect(el.classList.contains('empty-state')).toBe(true);
    expect(el.querySelector('.empty-state__icon svg')).not.toBeNull();
    expect(el.querySelector('.empty-state__title')?.textContent).toBe('No agents yet');
    expect(el.querySelector('.empty-state__hint')?.textContent).toBe('Create one.');
    expect(el.querySelector('button')?.textContent).toBe('Go');
  });

  it('escapes the texts and applies variants and extra classes', () => {
    const el = render(
      renderEmptyStateHtml({ icon: '', title: '<b>x</b>', variant: 'success', compact: true, className: 'dashboard-empty' })
    );
    expect(el.querySelector('b')).toBeNull();
    expect(el.classList.contains('empty-state--success')).toBe(true);
    expect(el.classList.contains('empty-state--compact')).toBe(true);
    expect(el.classList.contains('dashboard-empty')).toBe(true);
    expect(el.querySelector('.empty-state__hint')).toBeNull();
  });
});
