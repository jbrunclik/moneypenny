/**
 * Unit tests for setIcon - static icons set without an innerHTML write
 */
import { describe, it, expect } from 'vitest';
import * as icons from '@/utils/icons';
import { AI_AVATAR, CHECK_ICON, CLOSE_ICON, createIconElement, setIcon, type IconHtml } from '@/utils/icons';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** The HTML serializer's form of the source markup: `<x .../>` becomes `<x ...></x>`. */
function serialized(markup: string): string {
  return markup.replace(/<(\w+)([^>]*?)\/>/g, '<$1$2></$1>');
}

const iconConstants = Object.entries(icons).filter(
  (entry): entry is [string, IconHtml] => typeof entry[1] === 'string'
);

describe('setIcon', () => {
  it.each(iconConstants)('renders %s exactly as its markup', (_name, markup) => {
    const el = document.createElement('span');
    setIcon(el, markup);
    expect(el.innerHTML).toBe(serialized(markup));
  });

  it('creates SVG elements in the SVG namespace', () => {
    const el = document.createElement('button');
    setIcon(el, CLOSE_ICON);
    expect(el.children).toHaveLength(1);
    expect(el.firstElementChild?.namespaceURI).toBe(SVG_NS);
    expect(el.querySelectorAll('line')).toHaveLength(2);
  });

  it('renders the avatar image as an HTML element', () => {
    const el = document.createElement('div');
    setIcon(el, AI_AVATAR);
    const img = el.querySelector('img');
    expect(img?.className).toBe('ai-avatar-img');
    expect(img?.getAttribute('src')).toBe('/static/avatar.png');
  });

  it('replaces existing children', () => {
    const el = document.createElement('button');
    el.append(document.createElement('b'), 'text');
    setIcon(el, CLOSE_ICON);
    setIcon(el, CHECK_ICON);
    expect(el.innerHTML).toBe(serialized(CHECK_ICON));
  });

  it('gives every element its own nodes', () => {
    const first = document.createElement('span');
    const second = document.createElement('span');
    setIcon(first, CLOSE_ICON);
    first.querySelector('line')?.setAttribute('x1', '0');
    setIcon(second, CLOSE_ICON);
    expect(second.innerHTML).toBe(serialized(CLOSE_ICON));
    expect(first.firstChild).not.toBe(second.firstChild);
  });

  it('accepts only icon constants', () => {
    const el = document.createElement('span');
    // @ts-expect-error a plain string is not trusted icon markup
    expect(() => setIcon(el, '<svg></svg>')).not.toThrow();
  });
});

describe('createIconElement', () => {
  it('wraps an icon in an element of the given class', () => {
    expect(createIconElement('section-icon', CHECK_ICON).outerHTML).toBe(`<span class="section-icon">${serialized(CHECK_ICON)}</span>`);
    expect(createIconElement('empty-state__icon', CLOSE_ICON, 'div').outerHTML).toBe(
      `<div class="empty-state__icon">${serialized(CLOSE_ICON)}</div>`
    );
  });
});
