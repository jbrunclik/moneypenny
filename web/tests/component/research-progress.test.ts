import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/api/conversations', () => ({
  conversations: { finishNow: vi.fn(() => Promise.resolve()) },
  messages: {},
}));
vi.mock('@/core/deep-research', () => ({ startDeepResearch: vi.fn(), declineDeepResearch: vi.fn() }));
import { conversations } from '@/api/conversations';
import {
  _resetResearchProgress,
  applyResearchEvent,
  finishResearchMessage,
  initResearchProgress,
  renderResearchProgress,
  type ResearchProgress,
} from '@/components/messages/research-progress';
import type { ResearchOffer, ResearchRun } from '@/types/api';

const START = Date.parse('2026-10-03T10:00:00Z');

function bubble(): HTMLElement {
  document.body.innerHTML = '<div id="messages"><div class="message assistant streaming"><div class="message-content-wrapper"><div class="message-content"></div></div></div></div>';
  initResearchProgress();
  return document.querySelector<HTMLElement>('.message')!;
}

function run(events: Record<string, unknown>[]): ResearchProgress {
  let progress: ResearchProgress | undefined;
  for (const event of events) progress = applyResearchEvent(progress, event as never);
  return progress!;
}

const PLAN = { type: 'research_plan', items: ['Ceny?', 'Doba?', 'Doklady?'], minutes: 5, started_at: START };
const lines = () => [...document.querySelectorAll('.research-progress__item')].map((li) => li.textContent!.replace(/\s+/g, ' ').trim());

describe('research progress panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetResearchProgress();
  });

  it('shows one line per item with its state', () => {
    const el = bubble();
    const progress = run([
      PLAN,
      { type: 'research_item', index: 0, status: 'started' },
      { type: 'research_item', index: 0, status: 'done', pages: 7 },
      { type: 'research_item', index: 1, status: 'waiting' },
      { type: 'research_item', index: 2, status: 'timed_out', pages: 1 },
    ]);
    renderResearchProgress(el, progress, { convId: 'c1', messageId: 'a1' }, START + 192_000);
    expect(lines()).toEqual(['✓ Ceny? 7 pages', '◷ Doba?', '⏱ Doklady? 1 page']);
    expect(el.querySelector('.research-progress__elapsed')!.textContent).toBe('3:12 · ~5 min');
    // One of three finished (done, failed, skipped and timed out all count)
    expect(el.querySelector<HTMLElement>('.research-progress__bar span')!.style.width).toBe('67%');
  });

  it('marks running, failed and skipped items', () => {
    const el = bubble();
    const progress = run([
      PLAN,
      { type: 'research_item', index: 0, status: 'started' },
      { type: 'research_item', index: 1, status: 'failed', pages: 0 },
      { type: 'research_item', index: 2, status: 'skipped', pages: 0 },
    ]);
    renderResearchProgress(el, progress, { convId: 'c1', messageId: 'a1' }, START);
    expect(el.querySelectorAll('.research-progress__item--started .research-progress__spinner')).toHaveLength(1);
    expect(lines().slice(1)).toEqual(['✕ Doba?', '– Doklady?']);
  });

  it('shows every finding with its agent number', () => {
    const el = bubble();
    const findings = [0, 1, 2, 3, 4, 5, 6].map((i) => ({ type: 'research_finding', agent: i % 3, text: `fakt ${i}` }));
    renderResearchProgress(el, run([PLAN, ...findings]), { convId: 'c1', messageId: 'a1' }, START);
    const feed = [...el.querySelectorAll('.research-progress__finding')].map((f) => f.textContent);
    expect(feed).toEqual(['① fakt 0', '② fakt 1', '③ fakt 2', '① fakt 3', '② fakt 4', '③ fakt 5', '① fakt 6']);
    expect(el.querySelector('.research-progress__label')!.textContent).toBe('Shared findings');
  });

  it('Finish now asks the server and shows Finishing…', async () => {
    const el = bubble();
    const progress = run([PLAN]);
    renderResearchProgress(el, progress, { convId: 'c1', messageId: 'a1' }, START);
    el.querySelector<HTMLButtonElement>('.research-progress__finish')!.click();
    expect(conversations.finishNow).toHaveBeenCalledWith('c1', 'a1');
    // A later event re-renders: the request is remembered
    renderResearchProgress(el, progress, { convId: 'c1', messageId: 'a1' }, START);
    const button = el.querySelector<HTMLButtonElement>('.research-progress__finish')!;
    expect(button.disabled).toBe(true);
    expect(button.textContent).toBe('Finishing…');
  });

  it('writing hides Finish now and says so', () => {
    const el = bubble();
    renderResearchProgress(el, run([PLAN, { type: 'research_sources', count: 12 }, { type: 'research_writing' }]), { convId: 'c1', messageId: 'a1' }, START);
    expect(el.querySelector('.research-progress__finish')).toBeNull();
    expect(el.querySelector('.research-progress__title')!.textContent).toBe('Writing the report from 12 sources…');
  });
});

describe('report chip and follow-up', () => {
  const RUN: ResearchRun = {
    round: 1,
    question: 'Q',
    context: '',
    offered_sub_questions: ['A', 'B'],
    sub_questions: ['Ceny?', 'Doba?'],
    items: [
      { status: 'done', pages: 20 },
      { status: 'timed_out', pages: 14 },
    ],
    pages_read: 34,
    board: [{ agent: 1, kind: 'finding', text: 'Cena 1 590 Kč', urls: [] }],
    cache_hits: 2,
    duration_ms: 371_000,
    estimate: { minutes: 5, cost_czk: 9 },
    finished_early: false,
  };

  it('done replaces the panel with the chip', () => {
    const el = bubble();
    renderResearchProgress(el, run([PLAN]), { convId: 'c1', messageId: 'a1' }, START);
    finishResearchMessage(el, { id: 'a1', research: { run: RUN } });
    expect(el.querySelector('.research-progress')).toBeNull();
    const chip = el.querySelector<HTMLDetailsElement>('details.research-chip')!;
    expect(chip.querySelector('.research-chip__text')!.textContent).toBe('Deep research · 2 questions · 34 pages · 6 min');
    expect(chip.open).toBe(false);
    const detail = chip.querySelector('.research-chip__body')!.textContent!;
    expect(detail).toContain('Ceny?');
    expect(detail).toContain('20 pages');
    expect(detail).toContain('② Cena 1 590 Kč');
  });

  it('a finished-early run says so in the chip', () => {
    const el = bubble();
    finishResearchMessage(el, { id: 'a1', research: { run: { ...RUN, finished_early: true } } });
    expect(el.querySelector('.research-chip__text')!.textContent).toContain('finished early');
  });

  it('the follow-up offer appears under the report', () => {
    const el = bubble();
    const followup: ResearchOffer = {
      question: 'Q', context: '', sub_questions: ['Další?'], estimate: { minutes: 5, cost_czk: 5 },
      rates: { base_minutes: 2, per_wave_minutes: 2.5, parallelism: 4, base_czk: 3, per_item_czk: 2 },
      status: 'offered', autostart: false, kind: 'followup', round: 2,
    };
    finishResearchMessage(el, { id: 'a1', research: { run: { ...RUN, followup } } });
    expect(el.querySelector('.research-offer__title')!.textContent).toBe('Research further?');
  });

  it('a message without research gets neither', () => {
    const el = bubble();
    finishResearchMessage(el, { id: 'a1' });
    expect(el.querySelector('.research-chip, .research-offer')).toBeNull();
  });
});
