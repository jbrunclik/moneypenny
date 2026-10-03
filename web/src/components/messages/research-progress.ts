/**
 * Deep-research progress in the streaming bubble, and the report's chip.
 *
 * The panel is rendered from a ResearchProgress model built from the run's
 * SSE events (research_plan/item/finding/sources/writing). The model lives
 * with the stream, not the element: switching conversations re-creates the
 * bubble and the next event (or the elapsed-time tick) re-renders it. When
 * the run ends the panel gives way to the header chip, expandable to the
 * plan, pages per item and the agents' shared findings.
 */
import { conversations } from '../../api/conversations';
import type { Message, ResearchRun } from '../../types/api';
import { MS_PER_MINUTE } from '../../constants';
import { escapeHtml } from '../../utils/dom';
import { createLogger } from '../../utils/logger';
import { renderResearchOffer } from './research-offer';

const log = createLogger('research-progress');

const PANEL_CLASS = 'research-progress';
const CHIP_CLASS = 'research-chip';
const FEED_SIZE = 5;
const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩';

export type ItemState = 'queued' | 'waiting' | 'started' | 'done' | 'failed' | 'skipped' | 'timed_out';

export interface ResearchProgress {
  items: string[];
  states: ItemState[];
  pages: number[];
  findings: { agent: number; text: string }[];
  /** Epoch ms the run started (server clock, survives a journal replay) */
  startedAt: number;
  minutes?: number;
  sources?: number;
  writing: boolean;
}

type ResearchEvent = { type: string; [key: string]: unknown };

/** Runs whose Finish now was pressed (by assistant message id) */
const finishRequested = new Set<string>();
const wired = new WeakSet<HTMLElement>();

/** Test hook */
export function _resetResearchProgress(): void {
  finishRequested.clear();
}

/** ① for agent 0, ② for agent 1, ... (#11 beyond ten) - as the server labels them. */
export function agentLabel(agent: number): string {
  return agent < CIRCLED.length ? CIRCLED[agent] : `#${agent + 1}`;
}

/** The model after one event (undefined until research_plan arrives). */
export function applyResearchEvent(progress: ResearchProgress | undefined, event: ResearchEvent): ResearchProgress | undefined {
  if (event.type === 'research_plan') {
    const items = (event.items as string[]) ?? [];
    return {
      items,
      states: items.map(() => 'queued'),
      pages: items.map(() => 0),
      findings: [],
      startedAt: typeof event.started_at === 'number' ? event.started_at : Date.now(),
      minutes: typeof event.minutes === 'number' ? event.minutes : undefined,
      writing: false,
    };
  }
  if (!progress) return progress;
  if (event.type === 'research_item') {
    const index = event.index as number;
    if (index in progress.states) {
      progress.states[index] = event.status as ItemState;
      if (typeof event.pages === 'number') progress.pages[index] = event.pages;
    }
  } else if (event.type === 'research_finding') {
    progress.findings.push({ agent: event.agent as number, text: String(event.text ?? '') });
  } else if (event.type === 'research_sources') {
    progress.sources = event.count as number;
  } else if (event.type === 'research_writing') {
    progress.writing = true;
  }
  return progress;
}

function pagesText(n: number): string {
  return `${n} ${n === 1 ? 'page' : 'pages'}`;
}

function stateHtml(state: ItemState, pages: number): string {
  switch (state) {
    case 'started':
      return '<span class="research-progress__spinner" aria-label="researching"></span>';
    case 'done':
      return `✓ ${pagesText(pages)}`;
    case 'waiting':
      return '◷ waiting';
    case 'failed':
      return '✕ failed';
    case 'skipped':
      return '– skipped';
    case 'timed_out':
      return '⏱ timed out';
    default:
      return '';
  }
}

function clock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function panelHtml(progress: ResearchProgress, messageId: string, now: number): string {
  const items = progress.items
    .map(
      (q, i) => `<li class="research-progress__item research-progress__item--${progress.states[i]}">
        <span class="research-progress__question">${escapeHtml(q)}</span>
        <span class="research-progress__state">${stateHtml(progress.states[i], progress.pages[i])}</span>
      </li>`
    )
    .join('');
  const feed = progress.findings
    .slice(-FEED_SIZE)
    .map((f) => `<li class="research-progress__finding">${agentLabel(f.agent)} ${escapeHtml(f.text)}</li>`)
    .join('');
  const of = progress.minutes ? ` of ~${progress.minutes} min` : '';
  const finishing = finishRequested.has(messageId);
  const status = progress.writing
    ? `<span class="research-progress__status">Writing the report${progress.sources ? ` from ${progress.sources} sources` : ''}…</span>`
    : `<button type="button" class="research-progress__finish"${finishing ? ' disabled' : ''}>${finishing ? 'Finishing…' : 'Finish now'}</button>`;
  return `
    <ol class="research-progress__items">${items}</ol>
    ${feed ? `<ul class="research-progress__feed">${feed}</ul>` : ''}
    <div class="research-progress__footer">
      <span class="research-progress__elapsed">Elapsed ${clock(now - progress.startedAt)}${of}</span>
      ${status}
    </div>`;
}

/** Render (or refresh) the panel at the top of a streaming bubble. */
export function renderResearchProgress(
  messageEl: HTMLElement,
  progress: ResearchProgress,
  ids: { convId: string; messageId: string },
  now = Date.now()
): void {
  const wrapper = messageEl.querySelector('.message-content-wrapper');
  if (!wrapper) return;
  let panel = wrapper.querySelector<HTMLElement>(`:scope > .${PANEL_CLASS}`);
  if (!panel) {
    panel = document.createElement('div');
    panel.className = PANEL_CLASS;
    wrapper.prepend(panel);
  }
  panel.dataset.conversationId = ids.convId;
  panel.dataset.messageId = ids.messageId;
  panel.innerHTML = panelHtml(progress, ids.messageId, now);
}

/** The elapsed clock only (a once-a-second tick must not replace the button). */
export function tickResearchProgress(
  messageEl: HTMLElement,
  progress: ResearchProgress,
  ids: { convId: string; messageId: string },
  now = Date.now()
): void {
  const elapsed = messageEl.querySelector(`.${PANEL_CLASS} .research-progress__elapsed`);
  if (!elapsed) return renderResearchProgress(messageEl, progress, ids, now);
  const of = progress.minutes ? ` of ~${progress.minutes} min` : '';
  elapsed.textContent = `Elapsed ${clock(now - progress.startedAt)}${of}`;
}

function onFinishNow(e: Event): void {
  const button = (e.target as Element).closest<HTMLButtonElement>('.research-progress__finish');
  const panel = button?.closest<HTMLElement>(`.${PANEL_CLASS}`);
  const { conversationId, messageId } = panel?.dataset ?? {};
  if (!button || !conversationId || !messageId || finishRequested.has(messageId)) return;
  finishRequested.add(messageId);
  button.disabled = true;
  button.textContent = 'Finishing…';
  conversations.finishNow(conversationId, messageId).catch((error: unknown) => {
    log.warn('Finish now failed', { error, conversationId, messageId });
    finishRequested.delete(messageId);
    button.disabled = false;
    button.textContent = 'Finish now';
  });
}

/** Delegated Finish now on the message list (call once it exists). */
export function initResearchProgress(container = document.getElementById('messages')): void {
  if (!container || wired.has(container)) return;
  wired.add(container);
  container.addEventListener('click', onFinishNow);
}

function chipHtml(run: ResearchRun): string {
  const minutes = Math.max(1, Math.round(run.duration_ms / MS_PER_MINUTE));
  const n = run.sub_questions.length;
  const early = run.finished_early ? ' · finished early' : '';
  const summary = `Deep research · ${n} ${n === 1 ? 'question' : 'questions'} · ${pagesText(run.pages_read)} · ${minutes} min${early}`;
  const items = run.sub_questions
    .map((q, i) => {
      const item = run.items[i];
      const state = item ? stateHtml(item.status, item.pages) : '';
      return `<li><span class="research-progress__question">${escapeHtml(q)}</span> <span class="research-progress__state">${state}</span></li>`;
    })
    .join('');
  const board = run.board
    .map((b) => `<li>${agentLabel(b.agent)} ${b.kind === 'lead' ? 'lead: ' : ''}${escapeHtml(b.text)}</li>`)
    .join('');
  return `<summary>${escapeHtml(summary)}</summary>
    <div class="research-chip__body">
      <ol class="research-chip__items">${items}</ol>
      ${board ? `<ul class="research-chip__board">${board}</ul>` : ''}
    </div>`;
}

function renderResearchChip(messageEl: HTMLElement, run: ResearchRun): void {
  const wrapper = messageEl.querySelector('.message-content-wrapper');
  if (!wrapper) return;
  const chip = document.createElement('details');
  chip.className = CHIP_CLASS;
  chip.innerHTML = chipHtml(run);
  wrapper.prepend(chip);
}

/**
 * A finished (or loaded) assistant message: the progress panel gives way to
 * the report chip, and an open offer - initial or a report's follow-up - is
 * shown under the answer. `live` marks a reply that just arrived.
 */
export function finishResearchMessage(
  messageEl: HTMLElement,
  message: Pick<Message, 'id' | 'research'>,
  options: { live?: boolean } = {}
): void {
  messageEl.querySelectorAll(`.${PANEL_CLASS}, .${CHIP_CLASS}`).forEach((el) => el.remove());
  finishRequested.delete(message.id);
  if (message.research?.run) renderResearchChip(messageEl, message.research.run);
  renderResearchOffer(messageEl, message, options);
}
