/**
 * One empty-state component across the feature pages.
 */
import { describe, it, expect } from 'vitest';
import { createEmptyState } from '@/components/EmptyState';
import { ROBOT_ICON } from '@/utils/icons';

describe('createEmptyState', () => {
  it('builds icon, title, hint and the call to action, texts as text', () => {
    const cta = document.createElement('button');
    cta.textContent = 'Go';
    const el = createEmptyState({ icon: ROBOT_ICON, title: '<b>x</b>', hint: 'Create one.', cta, compact: true, className: 'x-empty' });
    expect([...el.classList]).toEqual(['empty-state', 'empty-state--compact', 'x-empty']);
    expect(el.querySelector('.empty-state__icon svg')).not.toBeNull();
    expect(el.querySelector('.empty-state__title')?.textContent).toBe('<b>x</b>');
    expect(el.querySelector('b')).toBeNull();
    expect(el.querySelector('.empty-state__hint')?.textContent).toBe('Create one.');
    expect(el.lastElementChild).toBe(cta);
  });

  it('applies the variant and leaves out an absent hint', () => {
    const el = createEmptyState({ icon: ROBOT_ICON, title: 'None', variant: 'success' });
    expect(el.classList.contains('empty-state--success')).toBe(true);
    expect(el.querySelector('.empty-state__hint')).toBeNull();
  });
});
