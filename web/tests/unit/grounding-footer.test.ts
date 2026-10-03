import { describe, expect, it } from 'vitest';
import { decorateGrounding, footerText, showGroundingChecking } from '@/components/messages/grounding';
import type { ClaimAnnotation } from '@/types/api';

const anns = (...verdicts: ClaimAnnotation['verdict'][]): ClaimAnnotation[] =>
  verdicts.map((verdict, i) => ({ type: 'claim', verdict, quote: `q${i}` }));

function bubble(text: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `<div class="message-content-wrapper"><div class="message-content"><p>${text}</p></div></div>`;
  return el;
}

describe('footerText', () => {
  it('counts sourced of total and each problem kind (Czech)', () => {
    const text = footerText(anns('supported', 'supported', 'not_found', 'contradicted'), { checked: true, source_count: 3 }, 'cs');
    expect(text).toBe('2 z 4 tvrzení ze zdrojů · 1 bez zdroje · 1 jinak než zdroj');
  });

  it('omits zero parts and uses English otherwise', () => {
    expect(footerText(anns('supported', 'not_found'), { checked: true, source_count: 1 }, 'en')).toBe(
      '1 of 2 claims from sources · 1 without a source'
    );
  });

  it('legacy footer counts claims that were not anchored', () => {
    expect(footerText(anns('not_found', 'not_found', 'not_found'), { checked: true, legacy: true }, 'cs')).toBe('3 bez zdroje');
  });
});

describe('decorateGrounding', () => {
  it('adds a footer after the content and is a button only with problems', () => {
    const el = bubble('q0 and q1');
    decorateGrounding(el, { annotations: anns('supported', 'not_found'), grounding: { checked: true, source_count: 1 }, language: 'en' });
    const footer = el.querySelector('.message-content + .grounding-footer')!;
    expect(footer.getAttribute('role')).toBe('button');

    const clean = bubble('q0');
    decorateGrounding(clean, { annotations: anns('supported'), grounding: { checked: true, source_count: 1 }, language: 'en' });
    expect(clean.querySelector('.grounding-footer')!.getAttribute('role')).toBeNull();
  });

  it('addMessageToUI decorates server messages', async () => {
    const { addMessageToUI } = await import('@/components/messages');
    const container = document.createElement('div');
    container.id = 'messages';
    document.body.appendChild(container);
    addMessageToUI(
      {
        id: 'm1',
        role: 'assistant',
        content: 'PřepiServis vyřídí přepis.',
        created_at: '2026-10-03T08:00:00',
        language: 'cs',
        annotations: [{ type: 'claim', verdict: 'not_found', quote: 'PřepiServis' }],
        grounding: { checked: true, legacy: true },
      },
      container
    );
    expect(container.querySelector('.claim')!.textContent).toBe('PřepiServis');
    expect(container.querySelector('.grounding-footer')!.textContent).toBe('1 bez zdroje');
  });

  it('replaces the checking state and does nothing without annotations', () => {
    const el = bubble('q0');
    showGroundingChecking(el, 'cs');
    expect(el.querySelector('.grounding-footer--checking')!.textContent).toBe('Ověřuji proti zdrojům…');
    decorateGrounding(el, { annotations: [], grounding: undefined, language: 'cs' });
    expect(el.querySelector('.grounding-footer')).toBeNull();
  });
});
