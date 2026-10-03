import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/core/quick-actions', () => ({ sendComposedText: vi.fn() }));
import { sendComposedText } from '@/core/quick-actions';
import { initClaimCard } from '@/components/ClaimCard';
import { decorateGrounding } from '@/components/messages/grounding';

function setup(): HTMLElement {
  document.body.innerHTML = '<div id="messages"></div>';
  const msg = document.createElement('div');
  msg.className = 'message assistant';
  msg.innerHTML = '<div class="message-content-wrapper"><div class="message-content"><p>PřepiServis: rychlost 24–48 hodin. Kurýr.</p></div></div>';
  document.getElementById('messages')!.appendChild(msg);
  decorateGrounding(msg, {
    language: 'cs',
    grounding: { checked: true, source_count: 1 },
    annotations: [
      { type: 'claim', verdict: 'not_found', quote: 'rychlost 24–48 hodin', reason: 'Stránky popisují jen SPZ Služby.' },
      { type: 'claim', verdict: 'supported', quote: 'Kurýr', source: 1, source_quote: 'Kurýr vyzvedne' },
    ],
  });
  initClaimCard();
  return msg;
}

describe('ClaimCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('opens on click with heading, reason and Dohledat', () => {
    setup();
    (document.querySelector('.claim') as HTMLElement).click();
    const card = document.getElementById('claim-card')!;
    expect(card.querySelector('.claim-card__heading')!.textContent).toBe('Ve zdrojích není');
    expect(card.textContent).toContain('Stránky popisují jen SPZ Služby.');
    (card.querySelector('.claim-card__lookup') as HTMLButtonElement).click();
    expect(sendComposedText).toHaveBeenCalledWith('Dohledej a ověř: rychlost 24–48 hodin');
  });

  it('a source number shows the passage and no Dohledat', () => {
    setup();
    (document.querySelector('sup.claim-cite') as HTMLElement).click();
    const card = document.getElementById('claim-card')!;
    expect(card.querySelector('blockquote')!.textContent).toBe('„Kurýr vyzvedne“');
    expect(card.querySelector('.claim-card__lookup')).toBeNull();
  });

  it('closes on Escape and on an outside click', () => {
    setup();
    (document.querySelector('.claim') as HTMLElement).click();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('claim-card')).toBeNull();
    (document.querySelector('.claim') as HTMLElement).click();
    document.body.click();
    expect(document.getElementById('claim-card')).toBeNull();
  });
});
