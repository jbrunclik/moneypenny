import { beforeEach, describe, expect, it } from 'vitest';
import { openSourcesPopup } from '@/components/SourcesPopup';
import { createPopupShell } from '@/components/InfoPopup';

function items(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>('#sources-popup .source-item')];
}

describe('SourcesPopup', () => {
  beforeEach(() => {
    document.body.replaceChildren(createPopupShell('sources-popup'));
  });

  it('links an https source to its URL', () => {
    openSourcesPopup([{ title: 'Example', url: 'https://example.com/page' }]);
    const [item] = items();
    expect(item!.tagName).toBe('A');
    expect(item!.getAttribute('href')).toBe('https://example.com/page');
    expect(item!.querySelector('.source-url')!.textContent).toBe('example.com');
  });

  it('does not make a javascript: or data: source URL clickable', () => {
    openSourcesPopup([
      { title: 'Evil', url: 'javascript:alert(1)' },
      { title: 'Data', url: 'data:text/html,<script>alert(1)</script>' },
      { title: 'Good', url: 'https://example.com' },
    ]);
    const [evil, data, good] = items();
    for (const el of [evil!, data!]) {
      expect(el.hasAttribute('href')).toBe(false);
      expect(el.closest('a[href]')).toBeNull();
    }
    expect(evil!.querySelector('.source-title')!.textContent).toBe('Evil');
    expect(good!.getAttribute('href')).toBe('https://example.com/');
  });

  it('still renders when a source URL does not parse', () => {
    openSourcesPopup([
      { title: 'Broken', url: 'not a url' },
      { title: 'Good', url: 'https://example.com' },
    ]);
    expect(items()).toHaveLength(2);
    expect(items()[0]!.hasAttribute('href')).toBe(false);
  });
});
