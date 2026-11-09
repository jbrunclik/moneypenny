/**
 * The deep-research card: a deep_research proposal (proposal-card.ts hands
 * this kind to renderResearchCard), whose body is an editor for the plan.
 *
 * Sub-questions can be edited, removed and added, the context line edited;
 * the estimate is recomputed live from the plan's rates (same formula as
 * src/agent/deep_research/estimate.py - the server recomputes it on start).
 * Start sends the plan as a chat turn (core/deep-research); Not now is the
 * card's shared decline. A started card collapses to one line linking to its
 * report; declined or expired ones use the generic resolved line. An
 * explicitly requested run (autostart) counts down in the editor first, so
 * the plan can still be tweaked; any edit pauses the countdown.
 */
import {
  DEEP_RESEARCH_AUTOSTART_SECONDS,
  DEEP_RESEARCH_MAX_CONTEXT_CHARS,
  DEEP_RESEARCH_MAX_ITEM_CHARS,
  DEEP_RESEARCH_MAX_SUB_QUESTIONS,
} from '../../config';
import { findActionReply } from './message-links';
import { useStore } from '../../state/store';
import { flashElement } from './action-row';
import type { Proposal, ResearchPlan, ResearchRates } from '../../types/api';
import { createElement } from '../../utils/dom';
import { CHECK_ICON, SPARKLES_ICON, createIconElement } from '../../utils/icons';

const CARD_CLASS = 'research-offer';
const DECLINE_LABEL = 'Not now';
const STARTED_TEXT = 'Deep research started';
// The estimate's amount is in the server's display currency (COST_CURRENCY)
const CURRENCY_LABEL = 'Kč';

/** Cards already auto-started in this page (a re-render must not start twice) */
const autostarted = new Set<string>();
const proposalsByCard = new WeakMap<HTMLElement, Proposal>();
/** Running autostart countdowns, by card */
const countdowns = new WeakMap<HTMLElement, ReturnType<typeof setInterval>>();
/** Seconds left of a card's countdown, by proposal: a re-render (the card
 *  synced, the reply re-decorated) picks it up where it was */
const secondsLeft = new Map<string, number>();
const wired = new WeakSet<HTMLElement>();

/** Which card Start was pressed on: its proposal and the reply showing it. */
export interface ResearchStartTarget {
  proposalId: string;
  messageId: string;
}

/** What Start does: core/deep-research, passed in at startup (F1). */
export interface ResearchOfferActions {
  start: (
    target: ResearchStartTarget,
    subQuestions: string[],
    context: string,
    options: { whenIdle?: boolean; minutes?: number }
  ) => Promise<boolean>;
}
// UI-local (F2): injected by startup (F1)
let actions: ResearchOfferActions | null = null;

/** Test hook: forget auto-started cards. */
export function _resetResearchOffers(): void {
  autostarted.clear();
  secondsLeft.clear();
}

export function estimateFrom(rates: ResearchRates, n: number): { minutes: number; cost: number } {
  const waves = Math.ceil(Math.max(n, 1) / Math.max(rates.parallelism, 1));
  return {
    minutes: Math.ceil(rates.base_minutes + waves * rates.per_wave_minutes),
    cost: Math.floor(rates.base_czk + n * rates.per_item_czk + 0.5),
  };
}

/** A textarea holding `text` (as its value: a leading newline is kept). */
function textarea(attributes: Record<string, string>, text: string): HTMLTextAreaElement {
  const field = createElement('textarea', attributes);
  field.textContent = text;
  return field;
}

function item(text: string): HTMLLIElement {
  return createElement('li', { class: 'research-offer__item' }, [
    textarea({ rows: '1', maxlength: String(DEEP_RESEARCH_MAX_ITEM_CHARS), 'aria-label': 'Research question' }, text),
    createElement('button', { type: 'button', class: 'research-offer__remove', 'aria-label': 'Remove question' }, ['✕']),
  ]);
}

function button(className: string, label: string, attributes: Record<string, string> = {}): HTMLButtonElement {
  return createElement('button', { type: 'button', class: className, ...attributes }, [label]);
}

function editor(plan: ResearchPlan): HTMLElement[] {
  const title = plan.kind === 'followup' ? 'Research further?' : 'Research this in depth?';
  const contextField = textarea(
    { rows: '2', maxlength: String(DEEP_RESEARCH_MAX_CONTEXT_CHARS), 'aria-label': 'Context', hidden: '' },
    plan.context
  );
  return [
    createElement('div', { class: 'proposal-card__header research-offer__head' }, [
      createIconElement('proposal-card__icon', SPARKLES_ICON),
      createElement('span', { class: 'proposal-card__summary' }, [title]),
      createElement('span', { class: 'research-offer__estimate' }, [
        createElement('span', { class: 'research-offer__tag research-offer__tag--time' }),
        createElement('span', { class: 'research-offer__tag research-offer__tag--cost' }),
      ]),
    ]),
    // Inline flow: the spaces between label, text and ✎ show
    createElement('div', { class: 'research-offer__context' }, [
      createElement('span', { class: 'research-offer__label' }, ['Context:']),
      ' ',
      createElement('span', { class: 'research-offer__context-text' }, [plan.context]),
      ' ',
      createElement('button', { type: 'button', class: 'research-offer__context-edit', 'aria-label': 'Edit context' }, [
        '✎',
      ]),
      ' ',
      contextField,
    ]),
    createElement('ol', { class: 'research-offer__items' }, plan.sub_questions.map(item)),
    button('research-offer__add', '+ Add a question or topic'),
    createElement('div', { class: 'proposal-card__actions research-offer__actions' }, [
      button('btn btn-primary btn-sm research-offer__start', 'Start'),
      button('btn btn-secondary btn-sm proposal-card__decline', DECLINE_LABEL, { 'data-proposal-decline': '' }),
    ]),
  ];
}

/** The reply a card sits under (its report is the reply to the Start it sent). */
function messageIdOf(card: HTMLElement): string | undefined {
  return card.closest<HTMLElement>('.message')?.dataset.messageId;
}

/** A started card links to its report once the report is in the conversation. */
function addReportLink(card: HTMLElement): void {
  const convId = useStore.getState().currentConversation?.id;
  const messageId = messageIdOf(card);
  const reportId = convId && messageId ? findActionReply(convId, messageId) : null;
  if (!reportId || card.querySelector('.research-offer__report')) return;
  const link = document.createElement('button');
  link.type = 'button';
  link.className = 'research-offer__report';
  link.dataset.reportId = reportId;
  link.textContent = 'Report below ↓';
  card.querySelector('.proposal-card__outcome')?.append(' · ', link);
}

/** Add Report below ↓ to started cards on screen (a report just arrived). */
export function refreshReportLinks(container: ParentNode = document): void {
  container.querySelectorAll<HTMLElement>(`.${CARD_CLASS}[data-started]`).forEach(addReportLink);
}

/** The started line: the resolved card's look, with the report link. */
function showStarted(card: HTMLElement): void {
  stopCountdown(card);
  card.className = `proposal-card proposal-card--deep-research proposal-card--resolved proposal-card--approved ${CARD_CLASS}`;
  card.dataset.started = 'true';
  card.replaceChildren(
    createIconElement('proposal-card__state-icon', CHECK_ICON),
    createElement('span', { class: 'proposal-card__outcome' }, [STARTED_TEXT])
  );
  addReportLink(card);
}

function items(card: HTMLElement): string[] {
  return [...card.querySelectorAll<HTMLTextAreaElement>('.research-offer__item textarea')]
    .map((t) => t.value.trim())
    .filter(Boolean);
}

function context(card: HTMLElement): string {
  return card.querySelector<HTMLTextAreaElement>('.research-offer__context textarea')?.value.trim() ?? '';
}

/** Estimate, Start and Add states after any edit. */
function refresh(card: HTMLElement): void {
  const plan = proposalsByCard.get(card)?.research;
  if (!plan) return;
  const n = items(card).length;
  const { minutes, cost } = estimateFrom(plan.rates, n);
  const time = card.querySelector('.research-offer__tag--time');
  if (time) time.textContent = `~${minutes} min`;
  const costTag = card.querySelector('.research-offer__tag--cost');
  if (costTag) costTag.textContent = `~${cost} ${CURRENCY_LABEL}`;
  const startButton = card.querySelector<HTMLButtonElement>('.research-offer__start');
  if (startButton) startButton.disabled = n < 1 || n > DEEP_RESEARCH_MAX_SUB_QUESTIONS;
  const rows = card.querySelectorAll('.research-offer__item').length;
  const addButton = card.querySelector<HTMLButtonElement>('.research-offer__add');
  if (addButton) addButton.disabled = rows >= DEEP_RESEARCH_MAX_SUB_QUESTIONS;
}

function fillEditor(card: HTMLElement, proposal: Proposal): void {
  if (!proposal.research) return;
  card.className = `proposal-card proposal-card--deep-research ${CARD_CLASS}`;
  delete card.dataset.started;
  card.replaceChildren(...editor(proposal.research));
  refresh(card);
}

function start(card: HTMLElement, plan: string[], ctx: string, whenIdle = false): void {
  const proposal = proposalsByCard.get(card);
  const messageId = messageIdOf(card);
  if (!proposal?.research || !messageId) return;
  showStarted(card);
  const options = { ...(whenIdle && { whenIdle }), minutes: estimateFrom(proposal.research.rates, plan.length).minutes };
  void actions?.start({ proposalId: proposal.id, messageId }, plan, ctx, options).then((sent) => {
    // The card may have been re-rendered meanwhile: update the current one
    const current =
      document.querySelector<HTMLElement>(`.${CARD_CLASS}[data-proposal-id="${proposal.id}"]`) ?? card;
    // Not sent (a reply is still running): the editor comes back
    if (sent === false) {
      autostarted.delete(proposal.id);
      fillEditor(current, proposal);
    }
  });
}

/** Stop the card's countdown for good (the user acted, or it started). */
function stopCountdown(card: HTMLElement): void {
  const id = card.dataset.proposalId;
  if (id) secondsLeft.delete(id);
  const timer = countdowns.get(card);
  if (timer === undefined) return;
  clearInterval(timer);
  countdowns.delete(card);
  card.querySelector('.research-offer__countdown')?.remove();
  card.querySelector('.research-offer__edit')?.remove();
  const startButton = card.querySelector('.research-offer__start');
  if (startButton) startButton.textContent = 'Start';
}

/** The user sent a message: it answers or expires the cards, so no
 *  countdown may fire a Start after it (the card is no longer open). */
export function stopResearchCountdowns(): void {
  document.querySelectorAll<HTMLElement>(`.${CARD_CLASS}`).forEach(stopCountdown);
  secondsLeft.clear();
}

/** An explicitly requested run: start after a countdown the user can pause. */
function startCountdown(card: HTMLElement, from: number): void {
  const id = card.dataset.proposalId ?? '';
  let left = from;
  secondsLeft.set(id, left);
  const row = card.querySelector('.research-offer__actions');
  const startButton = card.querySelector('.research-offer__start');
  if (!row || !startButton) return;
  startButton.textContent = 'Start now';
  row.append(
    button('btn btn-secondary btn-sm research-offer__edit', 'Edit plan'),
    createElement('span', { class: 'research-offer__countdown' }, [`Starting in ${left} s`])
  );
  const label = card.querySelector<HTMLElement>('.research-offer__countdown');
  if (!label) return;
  countdowns.set(
    card,
    setInterval(() => {
      if (!card.isConnected) {
        // Re-rendered: its successor carries on from secondsLeft
        clearInterval(countdowns.get(card));
        countdowns.delete(card);
        return;
      }
      left -= 1;
      secondsLeft.set(id, left);
      if (left > 0) {
        label.textContent = `Starting in ${left} s`;
        return;
      }
      start(card, items(card), context(card), true);
    }, 1000)
  );
}

/** Scroll to and flash the report a started card links to. */
function flashReport(link: HTMLButtonElement): void {
  const report = document.querySelector<HTMLElement>(`.message[data-message-id="${link.dataset.reportId}"]`);
  if (report) flashElement(report, 'message--flash');
}

/** Show the context field in place of its text, focused. */
function editContext(card: HTMLElement, contextButton: HTMLButtonElement): void {
  const contextText = card.querySelector<HTMLElement>('.research-offer__context-text');
  if (contextText) contextText.hidden = true;
  contextButton.hidden = true;
  const field = card.querySelector<HTMLTextAreaElement>('.research-offer__context textarea');
  if (field) {
    field.hidden = false;
    field.focus();
  }
}

/** Plan edits: remove or add a question, edit the context. */
function editPlan(card: HTMLElement, target: HTMLButtonElement): void {
  if (target.classList.contains('research-offer__remove')) {
    target.closest('.research-offer__item')?.remove();
  } else if (target.classList.contains('research-offer__add')) {
    card.querySelector('.research-offer__items')?.append(item(''));
    card.querySelector<HTMLTextAreaElement>('.research-offer__item:last-child textarea')?.focus();
  } else if (target.classList.contains('research-offer__context-edit')) {
    editContext(card, target);
  }
}

function onClick(e: Event): void {
  const target = (e.target as Element).closest<HTMLButtonElement>(`.${CARD_CLASS} button`);
  const card = target?.closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!target || !card) return;
  if (target.classList.contains('research-offer__report')) return flashReport(target);
  if (target.classList.contains('research-offer__start')) return start(card, items(card), context(card));
  stopCountdown(card); // declining, or changing the plan
  if (target.dataset.proposalDecline !== undefined) return; // proposal-card.ts answers it
  if (target.classList.contains('research-offer__edit')) {
    card.querySelector<HTMLTextAreaElement>('.research-offer__item textarea')?.focus();
    return;
  }
  editPlan(card, target);
  refresh(card);
}

function onInput(e: Event): void {
  const card = (e.target as Element).closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!card) return;
  stopCountdown(card); // the user is changing the plan
  refresh(card);
}

/** Delegated listeners on the message list (call once it exists). */
export function initResearchOffers(
  offerActions: ResearchOfferActions,
  container = document.getElementById('messages')
): void {
  actions = offerActions;
  if (!container || wired.has(container)) return;
  wired.add(container);
  container.addEventListener('click', onClick);
  container.addEventListener('input', onInput);
}

/**
 * A deep_research card: the editor while pending, the started line once
 * approved; null for the other states (the generic resolved line). `live`
 * is set for a reply that just arrived: only then does an autostart count down.
 */
export function renderResearchCard(proposal: Proposal, options: { live?: boolean } = {}): HTMLElement | null {
  if (!proposal.research || (proposal.state !== 'pending' && proposal.state !== 'approved')) return null;
  const card = createElement('div', { 'data-proposal-id': proposal.id });
  proposalsByCard.set(card, proposal);
  if (proposal.state === 'approved') {
    showStarted(card);
    return card;
  }
  fillEditor(card, proposal);
  // Counts down once per page; a re-render carries on where it was
  const left = secondsLeft.get(proposal.id);
  if (left !== undefined) {
    startCountdown(card, left);
  } else if (proposal.research.autostart && options.live && !autostarted.has(proposal.id)) {
    autostarted.add(proposal.id);
    startCountdown(card, DEEP_RESEARCH_AUTOSTART_SECONDS);
  }
  return card;
}
