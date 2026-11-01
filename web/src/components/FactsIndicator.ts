/**
 * Conversation facts indicator.
 *
 * The agent keeps a short list of facts the user settled in this conversation
 * (corrections, decisions, things already done) and sees it with every turn
 * (src/api/helpers/conversation_facts.py). The list is read-only here: the
 * user changes a fact by saying so in the chat.
 *
 * Surfaces: a header chip (desktop chat header + mobile header) with the
 * count, and a popup listing the facts.
 */

import { conversations } from '../api/conversations';
import { useStore } from '../state/store';
import type { ConversationFactsResponse } from '../types/api';
import { createElement, getElementById } from '../utils/dom';
import { FACTS_ICON, setIcon } from '../utils/icons';
import { createPopup, createPopupShell, type PopupInstance } from './InfoPopup';

const POPUP_ID = 'facts-popup';
const EVENT_NAME = 'facts:open';
const CHIP_CLASS = 'chat-header-facts';
const CHIP_IDS = ['conversation-facts', 'conversation-facts-mobile'];

/** The open conversation's facts; null when it has none to show */
// UI-local (F2): the open conversation's chip only, refetched on every switch
let current: ConversationFactsResponse | null = null;

function factsForOpenConversation(): ConversationFactsResponse | null {
  if (current?.conversation_id !== useStore.getState().currentConversation?.id) {
    current = null;
  }
  return current;
}

function factsDetails(data: ConversationFactsResponse): HTMLElement[] {
  return [
    createElement('div', { class: 'facts-content' }, [
      createElement('p', { class: 'facts-intro' }, [
        'Facts settled in this conversation. Moneypenny sees them with every message and keeps them current.',
      ]),
      createElement(
        'ul',
        { class: 'facts-list' },
        data.facts.map((fact) =>
          createElement('li', { class: 'facts-item' }, [
            createElement('span', { class: 'facts-key' }, [fact.key]),
            createElement('span', { class: 'facts-text' }, [fact.text]),
          ])
        )
      ),
      createElement('p', { class: 'facts-note' }, ['To change a fact, tell Moneypenny in the chat.']),
    ]),
  ];
}

const factsPopup: PopupInstance<ConversationFactsResponse> = createPopup(
  {
    id: POPUP_ID,
    eventName: EVENT_NAME,
    icon: FACTS_ICON,
    title: 'Conversation Facts',
    styleClass: 'facts',
  },
  factsDetails
);

/** The popup's shell (embedded in the app shell by core/startup/app-shell.ts) */
export function createFactsPopupShell(): HTMLElement {
  return createPopupShell(POPUP_ID);
}

/** Initialize popup handlers and delegated clicks on the chips */
export function initFactsIndicator(): void {
  factsPopup.init();
  // Delegated: the desktop chip is re-created whenever the chat header re-renders
  document.addEventListener('click', (e) => {
    const target = e.target as HTMLElement | null;
    const data = factsForOpenConversation();
    if (data && target?.closest(`.${CHIP_CLASS}`)) factsPopup.open(data);
  });
}

function renderChips(): void {
  const data = factsForOpenConversation();
  for (const id of CHIP_IDS) {
    const chip = getElementById<HTMLElement>(id);
    if (!chip) continue;
    if (!data) {
      chip.classList.add('hidden');
      chip.textContent = '';
      continue;
    }
    chip.classList.remove('hidden');
    setIcon(chip, FACTS_ICON);
    chip.append(createElement('span', {}, [String(data.facts.length)]));
    const label = `${data.facts.length} ${data.facts.length === 1 ? 'fact' : 'facts'} settled in this conversation`;
    chip.title = label;
    chip.setAttribute('aria-label', label);
  }
}

/**
 * Fetch and render the facts of a conversation (null clears them).
 * Refreshed wherever the conversation cost chip refreshes.
 */
export async function updateFactsIndicator(convId: string | null): Promise<void> {
  if (!convId) {
    current = null;
    renderChips();
    return;
  }

  let data: ConversationFactsResponse | null;
  try {
    const response = await conversations.getFacts(convId);
    data = response.enabled && response.facts.length > 0 ? response : null;
  } catch {
    // Informational - hide it rather than surface an error
    data = null;
  }

  // The user may have switched conversations while the request was in flight
  if (useStore.getState().currentConversation?.id !== convId) return;
  current = data;
  renderChips();
}
