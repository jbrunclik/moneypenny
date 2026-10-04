import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/core/deep-research', () => ({
  startDeepResearch: vi.fn(() => Promise.resolve()),
  declineDeepResearch: vi.fn(() => Promise.resolve()),
}));
import { declineDeepResearch, startDeepResearch } from '@/core/deep-research';
import {
  _resetResearchOffers,
  estimateFrom,
  initResearchOffers,
  refreshReportLinks,
  renderResearchOffer,
} from '@/components/messages/research-offer';
import type { ResearchOffer } from '@/types/api';

const RATES = { base_minutes: 2, per_wave_minutes: 2.5, parallelism: 4, base_czk: 3, per_item_czk: 2 };

function offer(overrides: Partial<ResearchOffer> = {}): ResearchOffer {
  return {
    question: 'Přepis SPZ',
    context: 'rodina, Praha',
    sub_questions: ['Ceny agentur?', 'Kolik to trvá?', 'Co je potřeba?'],
    estimate: { minutes: 5, cost_czk: 9 },
    rates: RATES,
    status: 'offered',
    autostart: false,
    kind: 'initial',
    round: 1,
    ...overrides,
  };
}

function render(o: ResearchOffer | null, options?: { live?: boolean }): HTMLElement {
  document.body.innerHTML = '<div id="messages"><div class="message assistant" data-message-id="m1"><div class="message-content-wrapper"><div class="message-content"><p>Odpověď</p></div></div></div></div>';
  initResearchOffers();
  const el = document.querySelector<HTMLElement>('.message')!;
  renderResearchOffer(el, { id: 'm1', research: o ? { offer: o } : undefined }, options);
  return el;
}

const card = () => document.querySelector<HTMLElement>('.research-offer')!;
const meta = () => card().querySelector('.research-offer__estimate')!.textContent;
const items = () => [...card().querySelectorAll<HTMLTextAreaElement>('.research-offer__item textarea')];
const startBtn = () => card().querySelector<HTMLButtonElement>('.research-offer__start')!;
const addBtn = () => card().querySelector<HTMLButtonElement>('.research-offer__add')!;

function type(el: HTMLTextAreaElement, text: string): void {
  el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('estimateFrom', () => {
  it('rounds minutes up per wave and cost to the nearest unit', () => {
    expect(estimateFrom(RATES, 3)).toEqual({ minutes: 5, cost: 9 });
    expect(estimateFrom(RATES, 5)).toEqual({ minutes: 7, cost: 13 });
  });
});

describe('research offer card', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetResearchOffers();
  });

  it('shows the question, estimate, context and numbered items in English', () => {
    render(offer());
    expect(card().querySelector('.research-offer__title')!.textContent).toBe('Research this in depth?');
    expect(meta()).toBe('~5 min · ~9 Kč');
    expect(card().querySelector('.research-offer__context-text')!.textContent).toBe('rodina, Praha');
    expect(items().map((i) => i.value)).toEqual(['Ceny agentur?', 'Kolik to trvá?', 'Co je potřeba?']);
  });

  it('adding a question updates the estimate once it has text', () => {
    render(offer());
    addBtn().click();
    expect(items()).toHaveLength(4);
    expect(meta()).toBe('~5 min · ~9 Kč');
    type(items()[3], 'Online objednání?');
    expect(meta()).toBe('~5 min · ~11 Kč');
  });

  it('removing a question updates the estimate', () => {
    render(offer());
    card().querySelector<HTMLButtonElement>('.research-offer__remove')!.click();
    expect(items().map((i) => i.value)).toEqual(['Kolik to trvá?', 'Co je potřeba?']);
    expect(meta()).toBe('~5 min · ~7 Kč');
  });

  it('Start sends the edited items and context', () => {
    render(offer());
    type(items()[0], 'Ceny pražských agentur?');
    addBtn().click();
    type(items()[3], 'Online');
    addBtn().click(); // left empty: dropped
    card().querySelector<HTMLButtonElement>('.research-offer__context-edit')!.click();
    type(card().querySelector<HTMLTextAreaElement>('.research-offer__context textarea')!, 'rodina se dvěma dětmi');
    startBtn().click();
    expect(startDeepResearch).toHaveBeenCalledWith(
      'm1',
      ['Ceny pražských agentur?', 'Kolik to trvá?', 'Co je potřeba?', 'Online'],
      'rodina se dvěma dětmi',
      { minutes: 5 }
    );
    expect(card().textContent).toContain('Deep research started');
  });

  it('Start is disabled with no questions; Add is disabled at the limit', () => {
    render(offer({ sub_questions: ['A'] }));
    type(items()[0], '  ');
    expect(startBtn().disabled).toBe(true);
    render(offer({ sub_questions: ['1', '2', '3', '4', '5', '6', '7', '8'] }));
    expect(addBtn().disabled).toBe(true);
    expect(startBtn().disabled).toBe(false);
  });

  it('No thanks declines and collapses to one line', async () => {
    render(offer());
    card().querySelector<HTMLButtonElement>('.research-offer__decline')!.click();
    expect(declineDeepResearch).toHaveBeenCalledWith('m1');
    await vi.waitFor(() => expect(card().textContent).toBe('Deep research declined'));
  });

  it('autostart on a live reply starts once, showing Starting…', () => {
    const o = offer({ autostart: true });
    render(o, { live: true });
    expect(card().textContent).toContain('Starting…');
    render(o, { live: true });
    expect(startDeepResearch).toHaveBeenCalledTimes(1);
    expect(startDeepResearch).toHaveBeenCalledWith('m1', o.sub_questions, o.context, { whenIdle: true, minutes: 5 });
  });

  it('an autostart shows Deep research started once it is sent', async () => {
    render(offer({ autostart: true }), { live: true });
    await vi.waitFor(() => expect(card().textContent).toBe('Deep research started'));
  });

  it('an autostart that could not be sent falls back to the editor', async () => {
    vi.mocked(startDeepResearch).mockResolvedValueOnce(false);
    render(offer({ autostart: true }), { live: true });
    await vi.waitFor(() => expect(startBtn()).not.toBeNull());
  });

  it('autostart never fires from history', () => {
    render(offer({ autostart: true }));
    expect(startDeepResearch).not.toHaveBeenCalled();
    expect(startBtn()).not.toBeNull();
  });

  it('decided offers collapse; superseded ones show nothing', () => {
    render(offer({ status: 'started' }));
    expect(card().textContent).toBe('Deep research started');
    render(offer({ status: 'declined' }));
    expect(card().textContent).toBe('Deep research declined');
    render(offer({ status: 'superseded' }));
    expect(document.querySelector('.research-offer')).toBeNull();
    render(null);
    expect(document.querySelector('.research-offer')).toBeNull();
  });

  it('a started offer links to its report once it exists', async () => {
    const { useStore } = await import('@/state/store');
    const page = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 3 };
    useStore.setState({ currentConversation: { id: 'c1', title: 't', model: 'm', created_at: '', updated_at: '' } });
    useStore.getState().setMessages('c1', [
      { id: 'm1', role: 'assistant', content: 'x', created_at: '' },
      {
        id: 'u1', role: 'user', content: 'Start deep research', created_at: '',
        action: { type: 'deep_research', offer_message_id: 'm1', items: 3, minutes: 5 },
      },
    ], page);
    render(offer({ status: 'started' }));
    expect(card().textContent).toBe('Deep research started');
    useStore.getState().appendMessage('c1', { id: 'rep', role: 'assistant', content: 'Report', created_at: '' });
    const report = document.createElement('div');
    report.className = 'message assistant';
    report.dataset.messageId = 'rep';
    report.scrollIntoView = vi.fn();
    document.getElementById('messages')!.appendChild(report);
    refreshReportLinks();
    const link = card().querySelector<HTMLButtonElement>('.research-offer__report')!;
    expect(link.textContent).toBe('Report below ↓');
    link.click();
    expect(report.classList.contains('message--flash')).toBe(true);
  });

  it('a report follow-up offer renders the same editor', () => {
    document.body.innerHTML = '<div class="message assistant"><div class="message-content-wrapper"><div class="message-content"></div></div></div>';
    const el = document.querySelector<HTMLElement>('.message')!;
    const followup = offer({ kind: 'followup', round: 2, sub_questions: ['Další?'] });
    renderResearchOffer(el, { id: 'm2', research: { run: { round: 1, followup } as never } });
    expect(card().querySelector('.research-offer__title')!.textContent).toBe('Research further?');
  });
});
