/**
 * setSanitizedHtml is the one way computed HTML reaches the DOM (F3): it
 * takes only a SanitizedHtml, which the sanitizers produce - never a plain
 * string. (The @ts-expect-error lines fail the typecheck if that loosens.)
 */
import { describe, it, expect } from 'vitest';
import { setSanitizedHtml } from '@/utils/dom';
import { highlightCode, renderMarkdown } from '@/utils/markdown';

describe('setSanitizedHtml', () => {
  it('writes sanitizer output', () => {
    const el = document.createElement('div');
    setSanitizedHtml(el, renderMarkdown('**bold** <img src=x onerror="alert(1)">'));
    expect(el.querySelector('strong')?.textContent).toBe('bold');
    expect(el.querySelector('[onerror]')).toBeNull();

    setSanitizedHtml(el, highlightCode('<b>', 'xml'));
    expect(el.textContent).toBe('<b>');
    expect(el.querySelector('b')).toBeNull();
  });

  it('accepts no plain string', () => {
    const el = document.createElement('div');
    const html = '<img src=x onerror="alert(1)">';
    // @ts-expect-error a plain string is not SanitizedHtml
    expect(() => setSanitizedHtml(el, html)).not.toThrow();
    // @ts-expect-error neither is a template built from one
    setSanitizedHtml(el, `<p>${html}</p>`);
    expect(el.firstElementChild?.tagName).toBe('P');
  });
});
