import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decorateProposals, initProposalCards, type ProposalActions } from '@/components/messages/proposal-card';
import {
  _resetResearchOffers,
  estimateFrom,
  initResearchOffers,
  refreshReportLinks,
  stopResearchCountdowns,
  type ResearchOfferActions,
} from '@/components/messages/research-offer';
import type { Proposal, ResearchPlan } from '@/types/api';

function at<T>(items: ArrayLike<T>, i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item at index ${i}`);
  return item;
}

const startDeepResearch = vi.fn<ResearchOfferActions['start']>(() => Promise.resolve(true));
const declineProposal = vi.fn<ProposalActions['decline']>();
const approveProposal = vi.fn<ProposalActions['approve']>();
const replyProposal = vi.fn<ProposalActions['reply']>();

const RATES = { base_minutes: 2, per_wave_minutes: 2.5, parallelism: 4, base_czk: 3, per_item_czk: 2 };
const TARGET = { proposalId: 'p1', messageId: 'm1' };

function proposal(plan: Partial<ResearchPlan> = {}, state: Proposal['state'] = 'pending'): Proposal {
  return {
    id: 'p1',
    kind: 'deep_research',
    summary: 'Přepis SPZ',
    details: [],
    options: [{ label: 'Start', description: '' }],
    state,
    chosen: state === 'approved' ? 0 : null,
    result: state === 'approved' ? 'Started' : null,
    changes: null,
    research: {
      question: 'Přepis SPZ',
      context: 'rodina, Praha',
      sub_questions: ['Ceny agentur?', 'Kolik to trvá?', 'Co je potřeba?'],
      rates: RATES,
      autostart: false,
      kind: 'initial',
      ...plan,
    },
  };
}

function render(proposal: Proposal | null, options?: { live?: boolean }): HTMLElement {
  document.body.innerHTML = '<div id="messages"><div class="message assistant" data-message-id="m1"><div class="message-content-wrapper"><div class="message-content"><p>Odpověď</p></div></div></div></div>';
  initResearchOffers({ start: startDeepResearch });
  initProposalCards({ approve: approveProposal, decline: declineProposal, reply: replyProposal });
  const el = document.querySelector<HTMLElement>('.message')!;
  decorateProposals(el, { id: 'm1', proposals: proposal ? [proposal] : [] }, options);
  return el;
}

const card = () => document.querySelector<HTMLElement>('.research-offer')!;
const meta = () => [...card().querySelectorAll('.research-offer__tag')].map((t) => t.textContent).join(' · ');
const items = () => [...card().querySelectorAll<HTMLTextAreaElement>('.research-offer__item textarea')];
const startBtn = () => card().querySelector<HTMLButtonElement>('.research-offer__start')!;
const declineBtn = () => card().querySelector<HTMLButtonElement>('.proposal-card__decline')!;
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

describe('deep-research card', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetResearchOffers();
  });

  it('shows the question, estimate, context and numbered items in English', () => {
    render(proposal());
    expect(card().classList).toContain('proposal-card');
    expect(card().querySelector('.proposal-card__summary')!.textContent).toBe('Research this in depth?');
    expect(meta()).toBe('~5 min · ~9 Kč');
    expect(card().querySelector('.research-offer__context-text')!.textContent).toBe('rodina, Praha');
    expect(items().map((i) => i.value)).toEqual(['Ceny agentur?', 'Kolik to trvá?', 'Co je potřeba?']);
  });

  it('adding a question updates the estimate once it has text', () => {
    render(proposal());
    addBtn().click();
    expect(items()).toHaveLength(4);
    expect(meta()).toBe('~5 min · ~9 Kč');
    type(at(items(), 3), 'Online objednání?');
    expect(meta()).toBe('~5 min · ~11 Kč');
  });

  it('removing a question updates the estimate', () => {
    render(proposal());
    card().querySelector<HTMLButtonElement>('.research-offer__remove')!.click();
    expect(items().map((i) => i.value)).toEqual(['Kolik to trvá?', 'Co je potřeba?']);
    expect(meta()).toBe('~5 min · ~7 Kč');
  });

  it('Start sends the edited items and context', () => {
    render(proposal());
    type(at(items(), 0), 'Ceny pražských agentur?');
    addBtn().click();
    type(at(items(), 3), 'Online');
    addBtn().click(); // left empty: dropped
    card().querySelector<HTMLButtonElement>('.research-offer__context-edit')!.click();
    type(card().querySelector<HTMLTextAreaElement>('.research-offer__context textarea')!, 'rodina se dvěma dětmi');
    startBtn().click();
    expect(startDeepResearch).toHaveBeenCalledWith(
      TARGET,
      ['Ceny pražských agentur?', 'Kolik to trvá?', 'Co je potřeba?', 'Online'],
      'rodina se dvěma dětmi',
      { minutes: 5 }
    );
    expect(card().textContent).toContain('Deep research started');
  });

  it('Start is disabled with no questions; Add is disabled at the limit', () => {
    render(proposal({ sub_questions: ['A'] }));
    type(at(items(), 0), '  ');
    expect(startBtn().disabled).toBe(true);
    render(proposal({ sub_questions: ['1', '2', '3', '4', '5', '6', '7', '8'] }));
    expect(addBtn().disabled).toBe(true);
    expect(startBtn().disabled).toBe(false);
  });

  it('Not now is the card\'s decline; the card shows the outcome', async () => {
    declineProposal.mockResolvedValueOnce({ ...proposal(), state: 'declined' });
    render(proposal());
    declineBtn().click();
    expect(declineProposal).toHaveBeenCalledWith('p1');
    await vi.waitFor(() => expect(document.querySelector('.proposal-card')!.textContent?.trim()).toBe('Not now - Přepis SPZ'));
  });

  it('Not now stops the countdown', async () => {
    vi.useFakeTimers();
    declineProposal.mockResolvedValueOnce({ ...proposal(), state: 'declined' });
    render(proposal({ autostart: true }), { live: true });
    declineBtn().click();
    vi.advanceTimersByTime(20_000);
    vi.useRealTimers();
    expect(startDeepResearch).not.toHaveBeenCalled();
  });

  it('an explicit request counts down in the editor, then starts once', () => {
    vi.useFakeTimers();
    const o = proposal({ autostart: true });
    render(o, { live: true });
    expect(startBtn().textContent).toBe('Start now');
    expect(card().querySelector('.research-offer__countdown')!.textContent).toBe('Starting in 8 s');
    vi.advanceTimersByTime(3000);
    expect(card().querySelector('.research-offer__countdown')!.textContent).toBe('Starting in 5 s');
    expect(startDeepResearch).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5000);
    expect(startDeepResearch).toHaveBeenCalledTimes(1);
    expect(startDeepResearch).toHaveBeenCalledWith(TARGET, o.research!.sub_questions, o.research!.context, {
      whenIdle: true,
      minutes: 5,
    });
    vi.useRealTimers();
  });

  it('a re-render (the card synced) keeps counting down where it was', () => {
    vi.useFakeTimers();
    const p = proposal({ autostart: true });
    const el = render(p, { live: true });
    vi.advanceTimersByTime(3000);
    decorateProposals(el, { id: 'm1', proposals: [p] }); // not live: a sync re-decorated it
    expect(card().querySelector('.research-offer__countdown')!.textContent).toBe('Starting in 5 s');
    vi.advanceTimersByTime(5000);
    expect(startDeepResearch).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('sending a message stops every countdown (the card is answered or expires)', () => {
    vi.useFakeTimers();
    render(proposal({ autostart: true }), { live: true });
    vi.advanceTimersByTime(3000);
    stopResearchCountdowns();
    vi.advanceTimersByTime(20_000);
    expect(startDeepResearch).not.toHaveBeenCalled();
    expect(card().querySelector('.research-offer__countdown')).toBeNull();
    vi.useRealTimers();
  });

  it('a sync that re-decorates the reply keeps an edit in progress', () => {
    const p = proposal();
    const el = render(p);
    type(at(items(), 0), 'Ceny pražských agentur?');

    decorateProposals(el, { id: 'm1', proposals: [{ ...p }] }); // same card, same state

    expect(at(items(), 0).value).toBe('Ceny pražských agentur?');
  });

  it('editing the plan pauses the countdown', () => {
    vi.useFakeTimers();
    render(proposal({ autostart: true }), { live: true });
    type(at(items(), 0), 'Ceny pražských agentur?');
    vi.advanceTimersByTime(20_000);
    expect(startDeepResearch).not.toHaveBeenCalled();
    expect(card().querySelector('.research-offer__countdown')).toBeNull();
    expect(startBtn().textContent).toBe('Start');
    vi.useRealTimers();
  });

  it('Edit plan pauses the countdown and focuses the first question', () => {
    vi.useFakeTimers();
    render(proposal({ autostart: true }), { live: true });
    card().querySelector<HTMLButtonElement>('.research-offer__edit')!.click();
    vi.advanceTimersByTime(20_000);
    expect(startDeepResearch).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(items()[0]);
    vi.useRealTimers();
  });

  it('an autostart shows Deep research started once it is sent', async () => {
    vi.useFakeTimers();
    render(proposal({ autostart: true }), { live: true });
    vi.advanceTimersByTime(8000);
    vi.useRealTimers();
    await vi.waitFor(() => expect(card().textContent?.trim()).toBe('Deep research started'));
  });

  it('an autostart that could not be sent falls back to the editor', async () => {
    vi.mocked(startDeepResearch).mockResolvedValueOnce(false);
    vi.useFakeTimers();
    render(proposal({ autostart: true }), { live: true });
    vi.advanceTimersByTime(8000);
    vi.useRealTimers();
    await vi.waitFor(() => expect(startBtn()?.textContent).toBe('Start'));
  });

  it('autostart never fires from history', () => {
    render(proposal({ autostart: true }));
    expect(startDeepResearch).not.toHaveBeenCalled();
    expect(startBtn()).not.toBeNull();
  });

  it('a started card collapses to one line; declined and expired use the card\'s line', () => {
    render(proposal({}, 'approved'));
    expect(card().textContent?.trim()).toBe('Deep research started');
    render(proposal({}, 'declined'));
    expect(document.querySelector('.proposal-card')!.textContent?.trim()).toBe('Not now - Přepis SPZ');
    render(proposal({}, 'expired'));
    expect(document.querySelector('.proposal-card')!.textContent?.trim()).toBe('Expired - Přepis SPZ');
    render(null);
    expect(document.querySelector('.proposal-card')).toBeNull();
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
    render(proposal({}, 'approved'));
    expect(card().textContent?.trim()).toBe('Deep research started');
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
    render(proposal({ kind: 'followup', sub_questions: ['Další?'] }));
    expect(card().querySelector('.proposal-card__summary')!.textContent).toBe('Research further?');
  });
});
