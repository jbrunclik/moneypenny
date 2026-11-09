import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  decorateProposals,
  initProposalCards,
  renderProposalCard,
  type ProposalActions,
} from '../../src/components/messages/proposal-card';
import type { Proposal } from '../../src/types/api';

function proposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    id: 'p1',
    kind: 'schedule_item',
    summary: 'Reminder: "Call the plumber"',
    details: [
      { label: 'When', value: 'Fri 13 Nov 2026 08:00 (Europe/Prague)' },
      { label: 'Ends', value: 'then done' },
    ],
    options: [{ label: 'Set it up', description: '' }],
    state: 'pending',
    chosen: null,
    result: null,
    ...overrides,
  };
}

function reply(proposals: Proposal[]): HTMLElement {
  document.body.innerHTML = `<div id="messages"><div class="message assistant" data-message-id="m1">
    <div class="message-content-wrapper"><div class="message-content"><p>Shall I?</p></div></div></div></div>`;
  const el = document.querySelector<HTMLElement>('.message')!;
  decorateProposals(el, { id: 'm1', proposals });
  return el;
}

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

describe('proposal card', () => {
  let actions: ProposalActions;

  beforeEach(() => {
    actions = {
      approve: vi.fn(async () => proposal({ state: 'approved', chosen: 0, result: 'Reminder set - Fri 13 Nov 2026 08:00, then done.' })),
      decline: vi.fn(async () => proposal({ state: 'declined' })),
    };
  });

  it('renders the summary, details and one button per option', () => {
    const card = renderProposalCard(proposal());

    expect(card.querySelector('.proposal-card__summary')?.textContent).toBe('Reminder: "Call the plumber"');
    const rows = [...card.querySelectorAll('.proposal-card__row')].map((r) => r.textContent);
    expect(rows).toEqual(['WhenFri 13 Nov 2026 08:00 (Europe/Prague)', 'Endsthen done']);
    const buttons = [...card.querySelectorAll('button')].map((b) => b.textContent);
    expect(buttons).toEqual(['Set it up', 'Not now']);
  });

  it('approve calls the action and collapses to the result', async () => {
    const el = reply([proposal()]);
    initProposalCards(actions, document.getElementById('messages')!);

    el.querySelector<HTMLButtonElement>('[data-proposal-choice="0"]')!.click();
    await flush();

    expect(actions.approve).toHaveBeenCalledWith('p1', 0);
    const card = el.querySelector('.proposal-card')!;
    expect(card.classList.contains('proposal-card--resolved')).toBe(true);
    expect(card.textContent).toContain('Reminder set - Fri 13 Nov 2026 08:00, then done.');
    expect(card.querySelector('button')).toBeNull();
  });

  it('not now declines', async () => {
    const el = reply([proposal()]);
    initProposalCards(actions, document.getElementById('messages')!);

    el.querySelector<HTMLButtonElement>('[data-proposal-decline]')!.click();
    await flush();

    expect(actions.decline).toHaveBeenCalledWith('p1');
    expect(el.querySelector('.proposal-card')!.textContent).toContain('Not now');
  });

  it('failed shows the reason', () => {
    const card = renderProposalCard(proposal({ state: 'failed', result: 'That time has passed.' }));

    expect(card.classList.contains('proposal-card--failed')).toBe(true);
    expect(card.textContent).toContain('That time has passed.');
  });

  it('a 409 shows the card is no longer open', async () => {
    actions.approve = vi.fn(async () => {
      throw Object.assign(new Error('Conflict'), { status: 409 });
    });
    const el = reply([proposal()]);
    initProposalCards(actions, document.getElementById('messages')!);

    el.querySelector<HTMLButtonElement>('[data-proposal-choice="0"]')!.click();
    await flush();

    const card = el.querySelector('.proposal-card')!;
    expect(card.textContent).toContain('already answered');
    expect(card.querySelector('button')).toBeNull();
  });

  it('a network error keeps the card answerable', async () => {
    actions.approve = vi.fn(async () => {
      throw Object.assign(new Error('offline'), { status: 0 });
    });
    const el = reply([proposal()]);
    initProposalCards(actions, document.getElementById('messages')!);

    el.querySelector<HTMLButtonElement>('[data-proposal-choice="0"]')!.click();
    await flush();

    const button = el.querySelector<HTMLButtonElement>('[data-proposal-choice="0"]')!;
    expect(button.disabled).toBe(false);
    expect(el.querySelector('.proposal-card__error')?.textContent).toContain('try again');
  });

  it('decorating again replaces the cards in place (no duplicates)', () => {
    const el = reply([proposal()]);
    decorateProposals(el, { id: 'm1', proposals: [proposal({ state: 'expired' })] });

    expect(el.querySelectorAll('.proposal-card')).toHaveLength(1);
    expect(el.querySelector('.proposal-card')!.textContent).toContain('Expired');
  });
});
