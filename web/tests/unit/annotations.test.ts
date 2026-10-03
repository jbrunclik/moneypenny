import { describe, expect, it } from 'vitest';
import { applyAnnotations } from '@/components/messages/annotations';
import { renderMarkdown } from '@/utils/markdown';
import type { ClaimAnnotation } from '@/types/api';

function render(md: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message-content';
  el.innerHTML = renderMarkdown(md);
  return el;
}

const claim = (over: Partial<ClaimAnnotation>): ClaimAnnotation => ({
  type: 'claim',
  verdict: 'not_found',
  quote: '',
  ...over,
});

describe('applyAnnotations', () => {
  it('underlines a not_found claim', () => {
    const el = render('Rychlost: 24–48 hodin.');
    applyAnnotations(el, [claim({ quote: '24–48 hodin' })]);
    const span = el.querySelector('.claim')!;
    expect(span.textContent).toBe('24–48 hodin');
    expect(span.classList.contains('claim--not_found')).toBe(true);
  });

  it('anchors a quote written with markdown emphasis and links', () => {
    const el = render('**SPZ Služby** ([spzsluzby.cz](https://spzsluzby.cz)) a `registr-vozidel.cz`');
    const anchored = applyAnnotations(el, [
      claim({ quote: '**SPZ Služby**' }),
      claim({ quote: '[spzsluzby.cz](https://spzsluzby.cz)' }),
    ]);
    expect([...anchored]).toEqual([0, 1]);
    expect([...el.querySelectorAll('.claim')].map((s) => s.textContent)).toEqual(['SPZ Služby', 'spzsluzby.cz']);
  });

  it('spans a quote across bold boundaries', () => {
    const el = render('nesmí být starší než **1 rok** od novely');
    applyAnnotations(el, [claim({ quote: 'než **1 rok** od' })]);
    const text = [...el.querySelectorAll('.claim[data-claim="0"]')].map((s) => s.textContent).join('');
    expect(text).toBe('než 1 rok od');
  });

  it('picks the occurrence that matches the prefix', () => {
    const el = render('A: 1 590 Kč + 800 Kč. B: 1 200 Kč + 800 Kč.');
    applyAnnotations(el, [claim({ quote: '800 Kč', prefix: 'B: 1 200 Kč + ' })]);
    const span = el.querySelector('.claim')!;
    expect(span.previousSibling?.textContent?.endsWith('1 200 Kč + ')).toBe(true);
  });

  it('adds a source number after a supported claim instead of an underline', () => {
    const el = render('Kurýr vyzvedne doklady.');
    applyAnnotations(el, [claim({ quote: 'Kurýr vyzvedne doklady', verdict: 'supported', source: 2 })]);
    expect(el.querySelector('.claim')).toBeNull();
    expect(el.querySelector('sup.claim-cite')!.textContent).toBe('2');
  });

  it('never anchors inside code blocks and skips missing quotes', () => {
    const el = render('```\nVyšehrad\n```\nOther text');
    const anchored = applyAnnotations(el, [claim({ quote: 'Vyšehrad' }), claim({ quote: 'Nowhere' })]);
    expect(anchored.size).toBe(0);
    expect(el.querySelector('.claim')).toBeNull();
  });
});
