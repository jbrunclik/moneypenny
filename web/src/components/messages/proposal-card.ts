/**
 * Proposal cards under a reply: the one way Moneypenny asks for a yes
 * (docs/features/proposals.md). A pending card shows what will happen and a
 * button per option plus "Not now"; the server applies the chosen option
 * exactly as shown. A resolved card collapses to one line: the result, or
 * why it could not be done. Replying "yes" in the chat answers it too (the
 * server resolves it before the turn), so a card can change under the user;
 * decorating is idempotent and replaces cards in place.
 */
import { useStore } from '../../state/store';
import type { Proposal } from '../../types/api';
import { createElement } from '../../utils/dom';
import {
  CHECK_ICON,
  CLOCK_ICON,
  CLOSE_ICON,
  ROBOT_ICON,
  SLIDERS_ICON,
  WARNING_ICON,
  createIconElement,
  type IconHtml,
} from '../../utils/icons';
import { createLogger } from '../../utils/logger';

const log = createLogger('proposals');

const LIST_CLASS = 'proposal-list';
const CARD_CLASS = 'proposal-card';
const DECLINE_LABEL = 'Not now';
const NOT_OPEN_TEXT = 'This card was already answered or is no longer open.';
const RETRY_TEXT = "Couldn't reach Moneypenny - try again.";

/** What the card's buttons do: api/proposals.ts, passed in at startup (F1). */
export interface ProposalActions {
  approve: (proposalId: string, choice: number) => Promise<Proposal>;
  decline: (proposalId: string) => Promise<Proposal>;
}

/** The pending card's icon tile, by kind (looked up at render: no import-time reads). */
function kindIcon(kind: string): IconHtml {
  if (kind === 'schedule_item') return CLOCK_ICON;
  if (kind === 'create_agent') return ROBOT_ICON;
  if (kind === 'edit_agent') return SLIDERS_ICON;
  return CHECK_ICON;
}

/** The resolved line's icon, by state. */
function stateIcon(state: Proposal['state']): IconHtml {
  if (state === 'approved') return CHECK_ICON;
  if (state === 'declined') return CLOSE_ICON;
  if (state === 'failed') return WARNING_ICON;
  return CLOCK_ICON;
}

// UI-local (F2): injected by startup (F1)
let actions: ProposalActions | null = null;
const wired = new WeakSet<HTMLElement>();

function details(proposal: Proposal): HTMLElement | null {
  const rows = proposal.details ?? [];
  if (!rows.length) return null;
  return createElement(
    'dl',
    { class: 'proposal-card__details' },
    rows.map((row) =>
      createElement('div', { class: 'proposal-card__row' }, [
        createElement('dt', {}, [row.label]),
        createElement('dd', {}, [row.value]),
      ])
    )
  );
}

function buttons(proposal: Proposal): HTMLElement {
  const choices = proposal.options.map((option, index) =>
    createElement(
      'button',
      {
        type: 'button',
        class: index === 0 ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm',
        'data-proposal-choice': String(index),
        ...(option.description ? { title: option.description } : {}),
      },
      [option.label]
    )
  );
  const decline = createElement(
    'button',
    { type: 'button', class: 'btn btn-secondary btn-sm proposal-card__decline', 'data-proposal-decline': '' },
    [DECLINE_LABEL]
  );
  return createElement('div', { class: 'proposal-card__actions' }, [...choices, decline]);
}

/** The one line a resolved card keeps. */
function outcomeText(proposal: Proposal): string {
  switch (proposal.state) {
    case 'approved':
      return proposal.result || 'Done.';
    case 'failed':
      return `Couldn't do it: ${proposal.result || 'something went wrong.'}`;
    case 'declined':
      return `${DECLINE_LABEL} - ${proposal.summary}`;
    case 'applying':
      return `Setting it up - ${proposal.summary}`;
    default:
      return `Expired - ${proposal.summary}`;
  }
}

/** One card: pending (summary, details, buttons) or resolved (one line). */
export function renderProposalCard(proposal: Proposal): HTMLElement {
  const card = createElement('div', {
    class: `${CARD_CLASS} ${CARD_CLASS}--${proposal.kind.replaceAll('_', '-')}`,
    'data-proposal-id': proposal.id,
  });
  if (proposal.state !== 'pending') {
    card.classList.add(`${CARD_CLASS}--resolved`, `${CARD_CLASS}--${proposal.state}`);
    card.append(
      createIconElement('proposal-card__state-icon', stateIcon(proposal.state)),
      createElement('span', { class: 'proposal-card__outcome' }, [outcomeText(proposal)])
    );
    return card;
  }
  card.append(
    createElement('div', { class: 'proposal-card__header' }, [
      createIconElement('proposal-card__icon', kindIcon(proposal.kind)),
      createElement('span', { class: 'proposal-card__summary' }, [proposal.summary]),
    ]),
    ...[details(proposal)].filter((n): n is HTMLElement => n !== null),
    buttons(proposal)
  );
  return card;
}

/** Render (or replace) a reply's cards under its text; none removes the list. */
export function decorateProposals(
  messageEl: HTMLElement,
  message: { id: string; proposals?: Proposal[] | null }
): void {
  const shown = message.proposals ?? [];
  let list = messageEl.querySelector<HTMLElement>(`.${LIST_CLASS}`);
  if (!shown.length) {
    list?.remove();
    return;
  }
  if (!list) {
    const content = messageEl.querySelector('.message-content');
    if (!content) return;
    list = createElement('div', { class: LIST_CLASS });
    content.insertAdjacentElement('afterend', list);
  }
  list.replaceChildren(...shown.map(renderProposalCard));
}

/** Keep the store's copy of the reply's cards in step with the screen. */
function storeOutcome(messageEl: HTMLElement, updated: Proposal): void {
  const convId = useStore.getState().currentConversation?.id;
  const messageId = messageEl.dataset.messageId;
  if (!convId || !messageId) return;
  const message = useStore.getState().getMessages(convId).find((m) => m.id === messageId);
  const proposals = (message?.proposals ?? []).map((p) => (p.id === updated.id ? updated : p));
  useStore.getState().updateMessage(convId, messageId, { proposals });
}

function showOutcome(card: HTMLElement, updated: Proposal): void {
  const messageEl = card.closest<HTMLElement>('.message');
  card.replaceWith(renderProposalCard(updated));
  if (messageEl) storeOutcome(messageEl, updated);
}

function showError(card: HTMLElement, error: unknown): void {
  const { status, details } = error as { status?: number; details?: { proposal?: Proposal } };
  if (status === 409 && details?.proposal) {
    showOutcome(card, details.proposal); // the other device's (or typed) answer
    return;
  }
  if (status === 409) {
    card.querySelector('.proposal-card__actions')?.remove();
    card.querySelector('.proposal-card__error')?.remove();
    card.append(createElement('p', { class: 'proposal-card__note' }, [NOT_OPEN_TEXT]));
    return;
  }
  for (const button of card.querySelectorAll<HTMLButtonElement>('button')) button.disabled = false;
  card.querySelector('.proposal-card__error')?.remove();
  card.append(createElement('p', { class: 'proposal-card__error', role: 'alert' }, [RETRY_TEXT]));
}

async function answer(card: HTMLElement, choice: number | null): Promise<void> {
  const id = card.dataset.proposalId;
  if (!actions || !id) return;
  for (const button of card.querySelectorAll<HTMLButtonElement>('button')) button.disabled = true;
  try {
    const updated = choice === null ? await actions.decline(id) : await actions.approve(id, choice);
    showOutcome(card, updated);
  } catch (error) {
    log.warn('Answering a proposal failed', { proposalId: id, error: String(error) });
    showError(card, error);
  }
}

function onClick(event: Event): void {
  const target = event.target as HTMLElement | null;
  const button = target?.closest<HTMLButtonElement>('button');
  const card = button?.closest<HTMLElement>(`.${CARD_CLASS}`);
  if (!button || !card || button.disabled) return;
  if (button.dataset.proposalChoice !== undefined) {
    void answer(card, Number(button.dataset.proposalChoice));
  } else if (button.dataset.proposalDecline !== undefined) {
    void answer(card, null);
  }
}

/** Wire the cards' buttons (event delegation on the messages list). */
export function initProposalCards(
  cardActions: ProposalActions,
  container = document.getElementById('messages')
): void {
  actions = cardActions;
  if (!container || wired.has(container)) return;
  wired.add(container);
  container.addEventListener('click', onClick);
}
