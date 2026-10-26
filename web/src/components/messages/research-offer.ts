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
import { findActionReply } from './message-links';
import { useStore } from '../../state/store';
import { flashElement } from './action-row';
import type { Message, MessageResearch, ResearchOffer, ResearchRates } from '../../types/api';
import { createElement } from '../../utils/dom';
import { SPARKLES_ICON, createIconElement } from '../../utils/icons';

const CARD_CLASS = 'research-offer';
// The estimate's amount is in the server's display currency (COST_CURRENCY)
const CURRENCY_LABEL = 'Kč';

/** Offers already auto-started in this page (a re-render must not start twice) */
const autostarted = new Set<string>();
const offersByCard = new WeakMap<HTMLElement, ResearchOffer>();
/** Running autostart countdowns, by card */
const countdowns = new WeakMap<HTMLElement, ReturnType<typeof setInterval>>();
const wired = new WeakSet<HTMLElement>();

/** What Start and No thanks do: core/deep-research, passed in at startup (F1). */
export interface ResearchOfferActions {
  start: (
    offerMessageId: string,
    subQuestions: string[],
    context: string,
    options: { whenIdle?: boolean; minutes?: number }
  ) => Promise<boolean>;
  decline: (offerMessageId: string) => Promise<boolean>;
}
let actions: ResearchOfferActions | null = null;

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

function button(className: string, label: string): HTMLButtonElement {
  return createElement('button', { type: 'button', class: className }, [label]);
}

function editor(offer: ResearchOffer): HTMLElement[] {
  const title = offer.kind === 'followup' ? 'Research further?' : 'Research this in depth?';
  const contextField = textarea(
    { rows: '2', maxlength: String(DEEP_RESEARCH_MAX_CONTEXT_CHARS), 'aria-label': 'Context', hidden: '' },
    offer.context
  );
  return [
    createElement('div', { class: 'research-offer__head' }, [
      createIconElement('research-offer__icon', SPARKLES_ICON),
      createElement('span', { class: 'research-offer__title' }, [title]),
      createElement('span', { class: 'research-offer__estimate' }, [
        createElement('span', { class: 'research-offer__tag research-offer__tag--time' }),
        createElement('span', { class: 'research-offer__tag research-offer__tag--cost' }),
      ]),
    ]),
    // Inline flow: the spaces between label, text and ✎ show
    createElement('div', { class: 'research-offer__context' }, [
      createElement('span', { class: 'research-offer__label' }, ['Context:']),
      ' ',
      createElement('span', { class: 'research-offer__context-text' }, [offer.context]),
      ' ',
      createElement('button', { type: 'button', class: 'research-offer__context-edit', 'aria-label': 'Edit context' }, [
        '✎',
      ]),
      ' ',
      contextField,
    ]),
    createElement('ol', { class: 'research-offer__items' }, offer.sub_questions.map(item)),
    button('research-offer__add', '+ Add a question or topic'),
    createElement('div', { class: 'research-offer__actions' }, [
      button('research-offer__start', 'Start'),
      button('research-offer__decline', 'No thanks'),
    ]),
  ];
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

function start(card: HTMLElement, plan: string[], ctx: string, whenIdle = false): void {
  const messageId = card.dataset.messageId;
  const offer = offersByCard.get(card);
  stopCountdown(card);
  collapseStarted(card);
  if (!messageId) return;
  const options = {
    ...(whenIdle && { whenIdle }),
    ...(offer && { minutes: estimateFrom(offer.rates, plan.length).minutes }),
  };
  void actions?.start(messageId, plan, ctx, options).then((sent) => {
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
  const actions = card.querySelector('.research-offer__actions');
  const startButton = card.querySelector('.research-offer__start');
  if (!actions || !startButton) return;
  startButton.textContent = 'Start now';
  actions.insertAdjacentHTML(
    'beforeend',
    '<button type="button" class="research-offer__edit">Edit plan</button><span class="research-offer__countdown"></span>'
  );
  const label = card.querySelector<HTMLElement>('.research-offer__countdown');
  if (!label) return;
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
  card.replaceChildren(...editor(offer));
  refresh(card);
}

/** Scroll to and flash the report a started offer links to. */
function flashReport(button: HTMLButtonElement): void {
  const report = document.querySelector<HTMLElement>(`.message[data-message-id="${button.dataset.reportId}"]`);
  if (report) flashElement(report, 'message--flash');
}

/** No thanks: decline on the server; the card goes away once that succeeds. */
function declineOffer(card: HTMLElement, button: HTMLButtonElement): void {
  stopCountdown(card);
  const messageId = card.dataset.messageId;
  if (!messageId) return;
  button.disabled = true;
  void actions?.decline(messageId).then((ok) => {
    if (ok === false) button.disabled = false;
    else card.remove(); // nothing left to act on
  });
}

/** Show the context field in place of its text, focused. */
function editContext(card: HTMLElement, button: HTMLButtonElement): void {
  const contextText = card.querySelector<HTMLElement>('.research-offer__context-text');
  if (contextText) contextText.hidden = true;
  button.hidden = true;
  const field = card.querySelector<HTMLTextAreaElement>('.research-offer__context textarea');
  if (field) {
    field.hidden = false;
    field.focus();
  }
}

/** Plan edits: remove or add a question, edit the context. */
function editPlan(card: HTMLElement, button: HTMLButtonElement): void {
  if (button.classList.contains('research-offer__remove')) {
    button.closest('.research-offer__item')?.remove();
  } else if (button.classList.contains('research-offer__add')) {
    card.querySelector('.research-offer__items')?.append(item(''));
    card.querySelector<HTMLTextAreaElement>('.research-offer__item:last-child textarea')?.focus();
  } else if (button.classList.contains('research-offer__context-edit')) {
    editContext(card, button);
  }
}

function onClick(e: Event): void {
  const button = (e.target as Element).closest<HTMLButtonElement>(`.${CARD_CLASS} button`);
  const card = button?.closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!button || !card) return;
  if (button.classList.contains('research-offer__report')) {
    flashReport(button);
    return;
  }
  if (button.classList.contains('research-offer__start')) {
    start(card, items(card), context(card));
    return;
  }
  if (button.classList.contains('research-offer__decline')) {
    declineOffer(card, button);
    return;
  }
  stopCountdown(card); // the user is changing the plan
  if (button.classList.contains('research-offer__edit')) {
    card.querySelector<HTMLTextAreaElement>('.research-offer__item textarea')?.focus();
    return;
  }
  editPlan(card, button);
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
