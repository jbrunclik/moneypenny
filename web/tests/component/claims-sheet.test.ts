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
    expect(document.querySelector('.claims-sheet__meta')!.textContent).toBe('Compared with 3 pages · 1 of 3 sourced');
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

  it('a sourced row names the source domain from the stored message', async () => {
    const { useStore } = await import('@/state/store');
    const msg = setup();
    msg.dataset.messageId = 'm-src';
    useStore.setState({ currentConversation: { id: 'c1' } } as never);
    vi.spyOn(useStore.getState(), 'getMessages').mockReturnValue([
      { id: 'm-src', role: 'assistant', content: '', created_at: '', sources: [{ title: 'A', url: 'https://www.spzsluzby.cz/x' }] },
    ] as never);
    (document.querySelector('.grounding-footer') as HTMLElement).click();
    const rows = [...document.querySelectorAll('.claims-sheet__row')];
    expect(rows[2].querySelector('.claims-sheet__detail')!.textContent).toBe('1 · spzsluzby.cz');
  });

  it('a sourced row without a known source list still names it as a source', () => {
    setup();
    (document.querySelector('.grounding-footer') as HTMLElement).click();
    const rows = [...document.querySelectorAll('.claims-sheet__row')];
    // Not a bare "1"
    expect(rows[2].querySelector('.claims-sheet__detail')!.textContent).toBe('Source 1');
  });

  it('moves focus to the first row and returns it to the footer on Escape', () => {
    setup();
    const footer = document.querySelector('.grounding-footer') as HTMLElement;
    footer.focus();
    footer.click();
    expect(document.activeElement).toBe(document.querySelector('.claims-sheet__row'));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('claims-sheet')).toBeNull();
    expect(document.activeElement).toBe(footer);
  });
});
