/**
 * The deep-research offer card under an answer: an editor for the plan.
 *
 * Sub-questions can be edited, removed and added, the context line edited;
 * the estimate is recomputed live from the offer's rates (same formula as
 * src/agent/deep_research/estimate.py - the server recomputes it on start).
 * A started offer collapses to one line (linking to its report); a declined
 * or superseded one shows nothing. An explicitly requested run (autostart)
 * counts down in the editor first, so the plan can still be tweaked; any
 * edit pauses the countdown.
 */
import {
  DEEP_RESEARCH_AUTOSTART_SECONDS,
  DEEP_RESEARCH_MAX_CONTEXT_CHARS,
  DEEP_RESEARCH_MAX_ITEM_CHARS,
  DEEP_RESEARCH_MAX_SUB_QUESTIONS,
} from '../../config';
import { declineDeepResearch, startDeepResearch } from '../../core/deep-research';
import { findActionReply } from '../../core/message-links';
import { useStore } from '../../state/store';
import { flashElement } from './action-row';
import type { Message, MessageResearch, ResearchOffer, ResearchRates } from '../../types/api';
import { escapeHtml } from '../../utils/dom';
import { SPARKLES_ICON } from '../../utils/icons';

const CARD_CLASS = 'research-offer';
// The estimate's amount is in the server's display currency (COST_CURRENCY)
const CURRENCY_LABEL = 'Kč';

/** Offers already auto-started in this page (a re-render must not start twice) */
const autostarted = new Set<string>();
const offersByCard = new WeakMap<HTMLElement, ResearchOffer>();
/** Running autostart countdowns, by card */
const countdowns = new WeakMap<HTMLElement, ReturnType<typeof setInterval>>();
const wired = new WeakSet<HTMLElement>();

/** Test hook: forget auto-started offers. */
export function _resetResearchOffers(): void {
  autostarted.clear();
}

export function estimateFrom(rates: ResearchRates, n: number): { minutes: number; cost: number } {
  const waves = Math.ceil(Math.max(n, 1) / Math.max(rates.parallelism, 1));
  return {
    minutes: Math.ceil(rates.base_minutes + waves * rates.per_wave_minutes),
    cost: Math.floor(rates.base_czk + n * rates.per_item_czk + 0.5),
  };
}

/** The open offer of a message: its own, or a report's follow-up. */
function offerOf(research: MessageResearch | undefined): ResearchOffer | undefined {
  return research?.offer ?? research?.run?.followup;
}

function itemHtml(text: string): string {
  return `<li class="research-offer__item">
      <textarea rows="1" maxlength="${DEEP_RESEARCH_MAX_ITEM_CHARS}" aria-label="Research question">${escapeHtml(text)}</textarea>
      <button type="button" class="research-offer__remove" aria-label="Remove question">✕</button>
    </li>`;
}

function editorHtml(offer: ResearchOffer): string {
  const title = offer.kind === 'followup' ? 'Research further?' : 'Research this in depth?';
  return `
    <div class="research-offer__head">
      <span class="research-offer__icon">${SPARKLES_ICON}</span>
      <span class="research-offer__title">${title}</span>
      <span class="research-offer__estimate">
        <span class="research-offer__tag research-offer__tag--time"></span>
        <span class="research-offer__tag research-offer__tag--cost"></span>
      </span>
    </div>
    <div class="research-offer__context">
      <span class="research-offer__label">Context:</span>
      <span class="research-offer__context-text">${escapeHtml(offer.context)}</span>
      <button type="button" class="research-offer__context-edit" aria-label="Edit context">✎</button>
      <textarea rows="2" maxlength="${DEEP_RESEARCH_MAX_CONTEXT_CHARS}" aria-label="Context" hidden>${escapeHtml(offer.context)}</textarea>
    </div>
    <ol class="research-offer__items">${offer.sub_questions.map(itemHtml).join('')}</ol>
    <button type="button" class="research-offer__add">+ Add a question or topic</button>
    <div class="research-offer__actions">
      <button type="button" class="research-offer__start">Start</button>
      <button type="button" class="research-offer__decline">No thanks</button>
    </div>`;
}

function collapse(card: HTMLElement, text: string): void {
  card.classList.add(`${CARD_CLASS}--decided`);
  card.textContent = text;
}

const STARTED_TEXT = 'Deep research started';

/** A started offer links to its report once the report is in the conversation. */
function addReportLink(card: HTMLElement): void {
  const convId = useStore.getState().currentConversation?.id;
  const reportId = convId && card.dataset.messageId ? findActionReply(convId, card.dataset.messageId) : null;
  if (!reportId || card.querySelector('.research-offer__report')) return;
  const link = document.createElement('button');
  link.type = 'button';
  link.className = 'research-offer__report';
  link.dataset.reportId = reportId;
  link.textContent = 'Report below ↓';
  card.append(' · ', link);
}

/** Add Report below ↓ to started offers on screen (a report just arrived). */
export function refreshReportLinks(container: ParentNode = document): void {
  container.querySelectorAll<HTMLElement>(`.${CARD_CLASS}[data-started]`).forEach(addReportLink);
}

function collapseStarted(card: HTMLElement): void {
  collapse(card, STARTED_TEXT);
  card.dataset.started = 'true';
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
  const offer = offersByCard.get(card);
  if (!offer) return;
  const n = items(card).length;
  const { minutes, cost } = estimateFrom(offer.rates, n);
  card.querySelector('.research-offer__tag--time')!.textContent = `~${minutes} min`;
  card.querySelector('.research-offer__tag--cost')!.textContent = `~${cost} ${CURRENCY_LABEL}`;
  card.querySelector<HTMLButtonElement>('.research-offer__start')!.disabled =
    n < 1 || n > DEEP_RESEARCH_MAX_SUB_QUESTIONS;
  const rows = card.querySelectorAll('.research-offer__item').length;
  card.querySelector<HTMLButtonElement>('.research-offer__add')!.disabled = rows >= DEEP_RESEARCH_MAX_SUB_QUESTIONS;
}

function start(card: HTMLElement, plan: string[], ctx: string, whenIdle = false): void {
  const messageId = card.dataset.messageId!;
  const offer = offersByCard.get(card);
  stopCountdown(card);
  collapseStarted(card);
  const minutes = offer ? estimateFrom(offer.rates, plan.length).minutes : undefined;
  const options = whenIdle ? { whenIdle, minutes } : { minutes };
  void startDeepResearch(messageId, plan, ctx, options).then((sent) => {
    // The card may have been re-rendered meanwhile: update the current one
    const current = document.querySelector<HTMLElement>(`.${CARD_CLASS}[data-message-id="${messageId}"]`) ?? card;
    // Not sent (a reply is still running): the editor comes back
    if (sent === false && offer) {
      autostarted.delete(messageId);
      fillEditor(current, offer);
    } else {
      collapseStarted(current);
    }
  });
}

function stopCountdown(card: HTMLElement): void {
  const timer = countdowns.get(card);
  if (timer === undefined) return;
  clearInterval(timer);
  countdowns.delete(card);
  card.querySelector('.research-offer__countdown')?.remove();
  card.querySelector('.research-offer__edit')?.remove();
  const button = card.querySelector('.research-offer__start');
  if (button) button.textContent = 'Start';
}

/** An explicitly requested run: start after a countdown the user can pause. */
function startCountdown(card: HTMLElement): void {
  let left = DEEP_RESEARCH_AUTOSTART_SECONDS;
  const actions = card.querySelector('.research-offer__actions')!;
  card.querySelector('.research-offer__start')!.textContent = 'Start now';
  actions.insertAdjacentHTML(
    'beforeend',
    '<button type="button" class="research-offer__edit">Edit plan</button><span class="research-offer__countdown"></span>'
  );
  const label = card.querySelector<HTMLElement>('.research-offer__countdown')!;
  label.textContent = `Starting in ${left} s`;
  countdowns.set(
    card,
    setInterval(() => {
      left -= 1;
      if (!card.isConnected) return stopCountdown(card);
      if (left > 0) {
        label.textContent = `Starting in ${left} s`;
        return;
      }
      start(card, items(card), context(card), true);
    }, 1000)
  );
}

function fillEditor(card: HTMLElement, offer: ResearchOffer): void {
  card.classList.remove(`${CARD_CLASS}--decided`);
  delete card.dataset.started;
  card.innerHTML = editorHtml(offer);
  refresh(card);
}

function onClick(e: Event): void {
  const button = (e.target as Element).closest<HTMLButtonElement>(`.${CARD_CLASS} button`);
  const card = button?.closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!button || !card) return;
  if (button.classList.contains('research-offer__report')) {
    const report = document.querySelector<HTMLElement>(`.message[data-message-id="${button.dataset.reportId}"]`);
    if (report) flashElement(report, 'message--flash');
    return;
  }
  if (!button.classList.contains('research-offer__start') && !button.classList.contains('research-offer__decline')) {
    stopCountdown(card); // the user is changing the plan
  }
  if (button.classList.contains('research-offer__edit')) {
    card.querySelector<HTMLTextAreaElement>('.research-offer__item textarea')?.focus();
    return;
  }
  if (button.classList.contains('research-offer__remove')) {
    button.closest('.research-offer__item')?.remove();
  } else if (button.classList.contains('research-offer__add')) {
    card.querySelector('.research-offer__items')!.insertAdjacentHTML('beforeend', itemHtml(''));
    card.querySelector<HTMLTextAreaElement>('.research-offer__item:last-child textarea')?.focus();
  } else if (button.classList.contains('research-offer__context-edit')) {
    card.querySelector<HTMLElement>('.research-offer__context-text')!.hidden = true;
    button.hidden = true;
    const field = card.querySelector<HTMLTextAreaElement>('.research-offer__context textarea')!;
    field.hidden = false;
    field.focus();
  } else if (button.classList.contains('research-offer__start')) {
    start(card, items(card), context(card));
    return;
  } else if (button.classList.contains('research-offer__decline')) {
    stopCountdown(card);
    button.disabled = true;
    void declineDeepResearch(card.dataset.messageId!).then((ok) => {
      if (ok === false) button.disabled = false;
      else card.remove(); // nothing left to act on
    });
    return;
  }
  refresh(card);
}

function onInput(e: Event): void {
  const card = (e.target as Element).closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!card) return;
  stopCountdown(card); // the user is changing the plan
  refresh(card);
}

/** Delegated listeners on the message list (call once it exists). */
export function initResearchOffers(container = document.getElementById('messages')): void {
  if (!container || wired.has(container)) return;
  wired.add(container);
  container.addEventListener('click', onClick);
  container.addEventListener('input', onInput);
}

/**
 * Render (or remove) the offer card of an assistant message. `live` is set
 * for a reply that just arrived: only then does an autostart offer start.
 */
export function renderResearchOffer(
  messageEl: HTMLElement,
  message: Pick<Message, 'id' | 'research'>,
  options: { live?: boolean } = {}
): void {
  messageEl.querySelector(`.${CARD_CLASS}`)?.remove();
  const offer = offerOf(message.research);
  if (!offer || offer.status === 'superseded' || offer.status === 'declined') return;
  const anchor = messageEl.querySelector('.grounding-footer') ?? messageEl.querySelector('.message-content');
  if (!anchor) return;
  const card = document.createElement('div');
  card.className = CARD_CLASS;
  card.dataset.messageId = message.id;
  anchor.after(card);
  offersByCard.set(card, offer);
  if (offer.status === 'started') return collapseStarted(card);
  fillEditor(card, offer);
  // Counts down once per page; a re-render shows the plain editor
  if (offer.autostart && options.live && !autostarted.has(message.id)) {
    autostarted.add(message.id);
    startCountdown(card);
  }
}
