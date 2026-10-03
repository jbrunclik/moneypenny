/**
 * The deep-research offer card under an answer: an editor for the plan.
 *
 * Sub-questions can be edited, removed and added, the context line edited;
 * the estimate is recomputed live from the offer's rates (same formula as
 * src/agent/deep_research/estimate.py - the server recomputes it on start).
 * A decided offer collapses to one line; a superseded one shows nothing.
 */
import {
  DEEP_RESEARCH_MAX_CONTEXT_CHARS,
  DEEP_RESEARCH_MAX_ITEM_CHARS,
  DEEP_RESEARCH_MAX_SUB_QUESTIONS,
} from '../../config';
import { declineDeepResearch, startDeepResearch } from '../../core/deep-research';
import type { Message, MessageResearch, ResearchOffer, ResearchRates } from '../../types/api';
import { escapeHtml } from '../../utils/dom';

const CARD_CLASS = 'research-offer';
// The estimate's amount is in the server's display currency (COST_CURRENCY)
const CURRENCY_LABEL = 'Kč';

/** Offers already auto-started in this page (a re-render must not start twice) */
const autostarted = new Set<string>();
const offersByCard = new WeakMap<HTMLElement, ResearchOffer>();
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
      <span class="research-offer__title">${title}</span>
      <span class="research-offer__estimate"></span>
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
  card.querySelector('.research-offer__estimate')!.textContent = `~${minutes} min · ~${cost} ${CURRENCY_LABEL}`;
  card.querySelector<HTMLButtonElement>('.research-offer__start')!.disabled =
    n < 1 || n > DEEP_RESEARCH_MAX_SUB_QUESTIONS;
  const rows = card.querySelectorAll('.research-offer__item').length;
  card.querySelector<HTMLButtonElement>('.research-offer__add')!.disabled = rows >= DEEP_RESEARCH_MAX_SUB_QUESTIONS;
}

function start(card: HTMLElement, plan: string[], ctx: string): void {
  const messageId = card.dataset.messageId!;
  const offer = offersByCard.get(card);
  collapse(card, 'Deep research started');
  void startDeepResearch(messageId, plan, ctx).then((sent) => {
    // Not sent (a reply is still running): the editor comes back
    if (sent === false && offer) fillEditor(card, offer);
  });
}

function fillEditor(card: HTMLElement, offer: ResearchOffer): void {
  card.classList.remove(`${CARD_CLASS}--decided`);
  card.innerHTML = editorHtml(offer);
  refresh(card);
}

function onClick(e: Event): void {
  const button = (e.target as Element).closest<HTMLButtonElement>(`.${CARD_CLASS} button`);
  const card = button?.closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!button || !card) return;
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
    button.disabled = true;
    void declineDeepResearch(card.dataset.messageId!).then((ok) => {
      if (ok === false) button.disabled = false;
      else collapse(card, 'Deep research declined');
    });
    return;
  }
  refresh(card);
}

function onInput(e: Event): void {
  const card = (e.target as Element).closest<HTMLElement>(`.${CARD_CLASS}`);
  if (card) refresh(card);
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
  if (!offer || offer.status === 'superseded') return;
  const anchor = messageEl.querySelector('.grounding-footer') ?? messageEl.querySelector('.message-content');
  if (!anchor) return;
  const card = document.createElement('div');
  card.className = CARD_CLASS;
  card.dataset.messageId = message.id;
  anchor.after(card);
  offersByCard.set(card, offer);
  if (offer.status === 'started') return collapse(card, 'Deep research started');
  if (offer.status === 'declined') return collapse(card, 'Deep research declined');
  if (offer.autostart && (options.live || autostarted.has(message.id))) {
    collapse(card, 'Starting…');
    if (!autostarted.has(message.id)) {
      autostarted.add(message.id);
      void startDeepResearch(message.id, offer.sub_questions, offer.context);
    }
    return;
  }
  fillEditor(card, offer);
}
