/**
 * One empty-state component across the feature pages.
 */
import { describe, it, expect } from 'vitest';
import { createEmptyState, renderEmptyStateHtml } from '@/components/EmptyState';
import { ROBOT_ICON } from '@/utils/icons';

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

describe('createEmptyState', () => {
  it('builds the same nodes as the markup, texts as text', () => {
    const cta = document.createElement('button');
    cta.textContent = 'Go';
    const el = createEmptyState({ icon: ROBOT_ICON, title: '<b>x</b>', hint: 'Create one.', cta, compact: true, className: 'x-empty' });
    const html = render(
      renderEmptyStateHtml({ icon: ROBOT_ICON, title: '<b>x</b>', hint: 'Create one.', ctaHtml: '<button>Go</button>', compact: true, className: 'x-empty' })
    );
    const squeeze = (markup: string) => markup.replace(/>\s+</g, '><');
    expect(squeeze(el.outerHTML)).toBe(squeeze(html.outerHTML));
    expect(el.querySelector('b')).toBeNull();
    expect(el.lastElementChild).toBe(cta);
  });

  it('leaves out an absent hint', () => {
    expect(createEmptyState({ icon: ROBOT_ICON, title: 'None' }).querySelector('.empty-state__hint')).toBeNull();
  });
});
