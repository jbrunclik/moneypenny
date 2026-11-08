/**
 * Scheduled items indicator.
 *
 * Reminders, check-ins, watchers and recurring checks set from a chat belong
 * to it (docs/features/agents.md). Surfaces: a header chip (desktop chat
 * header + mobile header) with the count, and a sheet listing the items -
 * when, how each ends - with cancel, pause/resume for watchers and
 * recurring checks, and Run for standing jobs (an agent's schedule). Hidden
 * when the chat has none.
 */

import { schedules } from '../api/schedules';
import { useStore } from '../state/store';
import type { ScheduledItem } from '../types/api';
import { createElement, getElementById } from '../utils/dom';
import { CLOCK_ICON, createIconElement, setIcon } from '../utils/icons';
import { createLogger } from '../utils/logger';
import { toast } from './Toast';
import { createPopup, createPopupShell, type PopupInstance } from './InfoPopup';
import { SCHEDULE_KIND_ICONS } from './messages/delivery-label';

const POPUP_ID = 'schedules-popup';
const EVENT_NAME = 'schedules:open';
const CHIP_CLASS = 'chat-header-schedules';
const CHIP_IDS = ['conversation-schedules', 'conversation-schedules-mobile'];
const PAUSABLE = new Set<ScheduledItem['kind']>(['watcher', 'recurring']);

const log = createLogger('components/ScheduleIndicator');

/** The open conversation's items; null when it has none to show */
// UI-local (F2): the open conversation's chip only, refetched on every switch
let current: { conversationId: string; items: ScheduledItem[] } | null = null;

function itemsForOpenConversation(): ScheduledItem[] | null {
  if (current?.conversationId !== useStore.getState().currentConversation?.id) current = null;
  return current?.items ?? null;
}

function pausedNote(item: ScheduledItem): string {
  if (item.status !== 'paused') return '';
  return item.paused_reason === 'failures' ? ' · paused after failing' : ' · paused';
}

function itemRow(item: ScheduledItem): HTMLElement {
  const actions: HTMLElement[] = [];
  if (item.standing) {
    actions.push(createElement('button', { type: 'button', class: 'schedule-item-run', 'data-item-id': item.id }, ['Run']));
  }
  if (PAUSABLE.has(item.kind)) {
    const paused = item.status === 'paused';
    actions.push(
      createElement('button', { type: 'button', class: 'schedule-item-pause', 'data-item-id': item.id, 'data-paused': String(paused) }, [
        paused ? 'Resume' : 'Pause',
      ])
    );
  }
  actions.push(createElement('button', { type: 'button', class: 'schedule-item-cancel', 'data-item-id': item.id }, ['Cancel']));
  const meta = `${item.when} · ${item.ends}${pausedNote(item)}`;
  return createElement('li', { class: 'schedule-item' }, [
    createIconElement('schedule-item-icon', SCHEDULE_KIND_ICONS[item.kind]),
    createElement('div', { class: 'schedule-item-body' }, [
      createElement('span', { class: 'schedule-item-title' }, [item.title]),
      createElement('span', { class: 'schedule-item-meta' }, [meta]),
    ]),
    createElement('div', { class: 'schedule-item-actions' }, actions),
  ]);
}

function sheetContent(items: ScheduledItem[]): HTMLElement[] {
  return [
    createElement('div', { class: 'schedules-content' }, [
      createElement('ul', { class: 'schedules-list' }, items.map(itemRow)),
      createElement('p', { class: 'schedules-note' }, ['Results arrive in this chat. Deleting the chat deletes them.']),
    ]),
  ];
}

const schedulesPopup: PopupInstance<ScheduledItem[]> = createPopup(
  { id: POPUP_ID, eventName: EVENT_NAME, icon: CLOCK_ICON, title: 'Scheduled in this chat', styleClass: 'schedules' },
  sheetContent
);

/** The popup's shell (embedded in the app shell by core/startup/app-shell.ts) */
export function createSchedulesPopupShell(): HTMLElement {
  return createPopupShell(POPUP_ID);
}

/** What a hand-started run came to, when the chat itself shows nothing */
const RUN_NOTES: Record<string, () => void> = {
  failed: () => toast.error('The run failed. Try again later.'),
  silent: () => toast.info('Nothing new to report.'),
  approval: () => toast.warning('Waiting for your approval in the chat.'),
};

/** Run a standing job: the button shows it is busy for the (long) run */
async function runJob(button: HTMLButtonElement, itemId: string): Promise<void> {
  button.disabled = true;
  button.textContent = 'Running…';
  try {
    const { status } = await schedules.run(itemId);
    RUN_NOTES[status]?.();
  } catch (error) {
    log.warn('Standing job run failed', { itemId, error });
    toast.error('Could not run it right now.');
  }
}

async function act(button: HTMLElement): Promise<void> {
  const itemId = button.dataset.itemId;
  const convId = useStore.getState().currentConversation?.id;
  if (!itemId || !convId) return;
  try {
    if (button.classList.contains('schedule-item-cancel')) await schedules.remove(itemId);
    else if (button instanceof HTMLButtonElement && button.classList.contains('schedule-item-run')) await runJob(button, itemId);
    else if (button.dataset.paused === 'true') await schedules.resume(itemId);
    else await schedules.pause(itemId);
  } catch (error) {
    log.warn('Scheduled item action failed', { itemId, error });
  }
  await updateScheduleIndicator(convId);
  const items = itemsForOpenConversation();
  if (items) schedulesPopup.open(items);
  else schedulesPopup.close();
}

/** Initialize popup handlers and delegated clicks on the chips and the sheet */
export function initScheduleIndicator(): void {
  schedulesPopup.init();
  // Delegated: the desktop chip is re-created whenever the chat header re-renders
  document.addEventListener('click', (e) => {
    const target = e.target as HTMLElement | null;
    const action = target?.closest<HTMLElement>('.schedule-item-cancel, .schedule-item-pause, .schedule-item-run');
    if (action) {
      void act(action);
      return;
    }
    const items = itemsForOpenConversation();
    if (items && target?.closest(`.${CHIP_CLASS}`)) schedulesPopup.open(items);
  });
}

function renderChips(): void {
  const items = itemsForOpenConversation();
  for (const id of CHIP_IDS) {
    const chip = getElementById<HTMLElement>(id);
    if (!chip) continue;
    if (!items) {
      chip.classList.add('hidden');
      chip.textContent = '';
      continue;
    }
    chip.classList.remove('hidden');
    setIcon(chip, CLOCK_ICON);
    chip.append(createElement('span', {}, [String(items.length)]));
    const label = `${items.length} scheduled in this chat`;
    chip.title = label;
    chip.setAttribute('aria-label', label);
  }
}

/**
 * Fetch and render the items of a conversation (null clears them).
 * Refreshed wherever the conversation cost chip refreshes.
 */
export async function updateScheduleIndicator(convId: string | null): Promise<void> {
  if (!convId) {
    current = null;
    renderChips();
    return;
  }
  let items: ScheduledItem[] | null;
  try {
    const response = await schedules.forConversation(convId);
    items = response.items.length > 0 ? response.items : null;
  } catch {
    // Informational - hide it rather than surface an error
    items = null;
  }
  // The user may have switched conversations while the request was in flight
  if (useStore.getState().currentConversation?.id !== convId) return;
  current = items ? { conversationId: convId, items } : null;
  renderChips();
}
