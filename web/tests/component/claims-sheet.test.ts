import { describe, expect, it, vi } from 'vitest';
import { initClaimsSheet } from '@/components/ClaimsSheet';
import { decorateGrounding } from '@/components/messages/grounding';

function setup(): HTMLElement {
  document.body.innerHTML = '<div id="messages"></div>';
  const msg = document.createElement('div');
  msg.className = 'message assistant';
  msg.innerHTML = '<div class="message-content-wrapper"><div class="message-content"><p>A je dobré. B stojí 1 200 Kč. C zavírá v 18:00.</p></div></div>';
  document.getElementById('messages')!.appendChild(msg);
  decorateGrounding(msg, {
    language: 'cs',
    grounding: { checked: true, source_count: 3 },
    annotations: [
      { type: 'claim', verdict: 'supported', quote: 'A je dobré', source: 1, source_quote: 'A' },
      { type: 'claim', verdict: 'not_found', quote: 'C zavírá v 18:00', reason: 'Není.' },
      { type: 'claim', verdict: 'contradicted', quote: 'B stojí 1 200 Kč', reason: 'Zdroj: 1 590 Kč' },
    ],
  });
  initClaimsSheet();
  return msg;
}

describe('ClaimsSheet', () => {
  it('opens from the footer with rows ordered by severity', () => {
    setup();
    (document.querySelector('.grounding-footer') as HTMLElement).click();
    const rows = [...document.querySelectorAll('.claims-sheet__row .claims-sheet__quote')].map((r) => r.textContent);
    expect(rows).toEqual(['B stojí 1 200 Kč', 'C zavírá v 18:00', 'A je dobré']);
    expect(document.querySelector('.claims-sheet__meta')!.textContent).toBe('Porovnáno se 3 stránkami · 1 z 3 podloženo');
  });

  it('a row closes the sheet, scrolls to the claim and flashes it', () => {
    vi.useFakeTimers();
    setup();
    const target = document.querySelector('.claim--contradicted') as HTMLElement;
    target.scrollIntoView = vi.fn();
    (document.querySelector('.grounding-footer') as HTMLElement).click();
    (document.querySelector('.claims-sheet__row') as HTMLElement).click();
    expect(document.getElementById('claims-sheet')).toBeNull();
    expect(target.scrollIntoView).toHaveBeenCalled();
    expect(target.classList.contains('claim--flash')).toBe(true);
    vi.runAllTimers();
    expect(target.classList.contains('claim--flash')).toBe(false);
    vi.useRealTimers();
  });
});
