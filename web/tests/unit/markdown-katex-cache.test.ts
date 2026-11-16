/**
 * Rendered formulas are cached: a streaming reply re-renders its whole text
 * every frame, and each formula went through KaTeX every time (Nov 16 2026).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import katex from 'katex';
import { renderMarkdown, _clearKatexCache } from '@/utils/markdown';
import { KATEX_CACHE_MAX_ENTRIES } from '@/config';

beforeEach(() => {
  _clearKatexCache();
  vi.restoreAllMocks();
});

describe('KaTeX cache', () => {
  it('renders one formula once however often the text renders', () => {
    const spy = vi.spyOn(katex, 'renderToString');
    renderMarkdown('Energy $E=mc^2$ here');
    renderMarkdown('Energy $E=mc^2$ here, and more');
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('caches inline and display forms apart', () => {
    const spy = vi.spyOn(katex, 'renderToString');
    renderMarkdown('$x^2$');
    renderMarkdown('$$x^2$$');
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it('never holds more than the cap', () => {
    const spy = vi.spyOn(katex, 'renderToString');
    for (let i = 0; i < KATEX_CACHE_MAX_ENTRIES + 10; i++) renderMarkdown(`$x_{${i}}$`);
    spy.mockClear();
    renderMarkdown('$x_{0}$'); // the oldest was evicted
    renderMarkdown(`$x_{${KATEX_CACHE_MAX_ENTRIES + 9}}$`); // the newest stays
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
