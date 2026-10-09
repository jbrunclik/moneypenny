import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from '@/state/store';
import { initActionRows } from '@/components/messages/action-row';
import { addMessageToUI } from '@/components/messages';
import type { Conversation, Message } from '@/types/api';

const CONV: Conversation = { id: 'c1', title: 'T', model: 'm', created_at: '2026-10-03T08:00:00', updated_at: '2026-10-03T08:00:00' };
const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 2 };
const ANSWER: Message = {
  id: 'a1',
  role: 'assistant',
  content: 'Castelli Flanders Warm stojí 3 000 Kč.',
  created_at: '2026-10-03T08:00:00',
  annotations: [{ type: 'claim', verdict: 'not_found', quote: 'Castelli Flanders Warm', prefix: '' }],
  grounding: { checked: true, source_count: 1 },
};
const LOOKUP: Message = {
  id: 'u1',
  role: 'user',
  content: 'Look up and verify: Castelli Flanders Warm',
  created_at: '2026-10-03T08:01:00',
  action: { type: 'verify_claim', source_message_id: 'a1', claim_index: 0, quote: 'Castelli Flanders Warm' },
};

function render(messages: Message[]): HTMLElement {
  document.body.innerHTML = '<div id="messages"></div>';
  const container = document.getElementById('messages')!;
  useStore.setState({ currentConversation: CONV });
  useStore.getState().setMessages('c1', messages, PAGE);
  for (const m of messages) addMessageToUI(m, container);
  initActionRows(container);
  return container;
}

const row = (id: string) => document.querySelector<HTMLElement>(`[data-message-id="${id}"]`)!;

describe('action rows', () => {
  beforeEach(() => {
    vi.useRealTimers();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('a look-up renders as a row, not a bubble', () => {
    render([ANSWER, LOOKUP]);
    const el = row('u1');
    expect(el.classList.contains('message--action')).toBe(true);
    expect(el.querySelector('.message-content')).toBeNull();
    expect(el.querySelector('.action-row__text')!.textContent).toBe('Looking up “Castelli Flanders Warm”');
    expect(el.querySelector('.action-row__source')!.textContent).toBe('from the answer above ↑');
  });

  it('↑ scrolls to the claim and flashes it', () => {
    render([ANSWER, LOOKUP]);
    row('u1').querySelector<HTMLButtonElement>('.action-row__source')!.click();
    const claim = row('a1').querySelector<HTMLElement>('[data-claim="0"]')!;
    expect(claim.scrollIntoView).toHaveBeenCalled();
    expect(claim.classList.contains('claim--flash')).toBe(true);
  });

  it('a missing source hides the link', () => {
    render([LOOKUP]);
    expect(row('u1').querySelector('.action-row__source')).toBeNull();
    const converted = { ...LOOKUP, id: 'u2', action: { ...LOOKUP.action!, source_message_id: null, claim_index: null } } as Message;
    render([ANSWER, converted]);
    expect(row('u2').querySelector('.action-row__source')).toBeNull();
  });

  it('a deep-research start says what started', () => {
    const offer: Message = { id: 'o1', role: 'assistant', content: 'Krátká odpověď', created_at: '2026-10-03T08:00:00' };
    const start: Message = {
      id: 'u3',
      role: 'user',
      content: 'Start deep research',
      created_at: '2026-10-03T08:01:00',
      action: { type: 'deep_research', offer_message_id: 'o1', items: 5, minutes: 6 },
    };
    render([offer, start]);
    expect(row('u3').querySelector('.action-row__text')!.textContent).toBe('Deep research started · 5 questions · ~6\u00a0min'); // "~6 min" never splits across lines
    row('u3').querySelector<HTMLButtonElement>('.action-row__source')!.click();
    expect(row('o1').classList.contains('message--flash')).toBe(true);
  });

  it('a failed action send still offers Retry and Discard', () => {
    render([ANSWER, { ...LOOKUP, status: 'failed' }]);
    expect(row('u1').querySelector('.message-send-status')).not.toBeNull();
  });
});
