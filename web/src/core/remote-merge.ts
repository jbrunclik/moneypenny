/**
 * Merge what another device changed into the OPEN conversation, in place.
 *
 * Replaces the "New messages available - Reload" banner for chats: the
 * latest page is fetched and diffed against what is rendered. New messages
 * are appended where they belong, keeping the scroll position, drafts and
 * pending sends (the banner's reload re-rendered everything and dropped
 * them). A reply the other device is still streaming is followed live from
 * the shared journal instead of showing up as an empty bubble. Rendered
 * messages the server no longer has (deleted, regenerated) or whose text
 * changed fall back to a full re-render - rare, and correctness first.
 */

import { conversations } from '../api/conversations';
import { addMessageToUI, lockOlderQuizBlocks, updateLatestAssistantMarker } from '../components/messages';
import { showNewMessagesPill } from '../components/ScrollToBottom';
import { useStore } from '../state/store';
import { getSyncManager } from '../sync/SyncManager';
import type { Message } from '../types/api';
import { getElementById, isScrolledToBottom } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { programmaticScrollToBottom } from '../utils/programmatic-scroll';
import { markAgentViewedAndRefresh, reloadCurrentConversation } from './conversation';
import { isTempConversation } from '../utils/conversation-id';
import { followRemoteStream } from './stream-resume';
import { confirmDelivery } from './send-delivery';

const log = createLogger('remote-merge');

// One merge at a time; a request during one runs after it - for the
// conversation open THEN (a switch meanwhile used to re-run the old one,
// which bailed, and the new one's merge was lost until its next change)
let inFlight: Promise<void> | null = null;
let pendingConvId: string | null = null;

/** Merge the open conversation's external changes (serialized). */
export function mergeExternalChanges(convId: string): Promise<void> {
  pendingConvId = convId;
  if (inFlight) return inFlight;
  inFlight = (async () => {
    while (pendingConvId !== null) {
      const next = pendingConvId;
      pendingConvId = null;
      await mergeOnce(next).catch((error: unknown) => {
        log.warn('Merging external changes failed', { error, conversationId: next });
      });
    }
  })().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/** Messages only this device has (not yet on the server). */
function isLocalOnly(message: Message): boolean {
  return message.status === 'pending' || message.status === 'failed';
}

/** Whether a merge into the open conversation must wait (or doesn't apply). */
function shouldSkipMerge(convId: string): boolean {
  const store = useStore.getState();
  if (isTempConversation(convId) || store.currentConversation?.id !== convId) return true;
  // Our own turn running here: its end applies the deferred change
  if (store.getActiveRequest(convId)) return true;
  // Viewing an older window (search jump): newer pages load on scroll
  return store.messagesPagination.get(convId)?.hasNewer === true;
}

/**
 * Whether the server's window rewrote what this device shows: a message
 * this device has from the window's span is gone (deleted elsewhere), or a
 * known message's content differs (edited elsewhere).
 */
export function serverRewroteHistory(local: readonly Message[], server: readonly Message[]): boolean {
  const localById = new Map(local.map((m) => [m.id, m]));
  const serverIds = new Set(server.map((m) => m.id));
  const windowStart = server[0]?.created_at;

  const vanished = local.some(
    (m) => !isLocalOnly(m) && windowStart !== undefined && m.created_at >= windowStart && !serverIds.has(m.id)
  );
  const edited = server.some((m) => {
    const known = localById.get(m.id);
    return known !== undefined && m.content !== '' && known.content !== '' && known.content !== m.content;
  });
  return vanished || edited;
}

/**
 * Reconcile what this device shows as unfinished with the server's copy:
 * unconfirmed sends the server has are confirmed, incomplete reply bubbles
 * the server has saved are dropped so the saved version renders.
 */
function reconcileUnfinished(
  convId: string,
  container: HTMLElement,
  local: readonly Message[],
  server: readonly Message[]
): void {
  const localById = new Map(local.map((m) => [m.id, m]));
  const serverIds = new Set(server.map((m) => m.id));

  // Sends shown as unconfirmed here that reached the server after all (a
  // closed tab's, or one whose response was lost): sent, no Retry
  for (const m of local) {
    if (isLocalOnly(m) && serverIds.has(m.id)) confirmDelivery(convId, m.id);
  }

  // A reply bubble left incomplete here (a stop whose done never came, a
  // recovery that gave up with partial text) has the reply's id but isn't in
  // the store: drop it so the server's saved version renders in its place
  for (const el of container.querySelectorAll<HTMLElement>('.message.message-incomplete[data-message-id]')) {
    const id = el.dataset.messageId;
    const saved = id !== undefined && !localById.has(id) ? server.find((m) => m.id === id) : undefined;
    if (saved && saved.content !== '') el.remove();
  }
}

/**
 * The messages list to merge into, or null when the conversation is no
 * longer open or our own turn started there while the fetch was in flight.
 */
function mergeContainerFor(convId: string): HTMLDivElement | null {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container || useStore.getState().currentConversation?.id !== convId) return null;
  if (useStore.getState().getActiveRequest(convId)) return null;
  return container;
}

function markAgentConversationViewed(response: { is_agent?: boolean | null; agent_id?: string | null }): void {
  if (response.is_agent && response.agent_id) markAgentViewedAndRefresh(response.agent_id);
}

async function mergeOnce(convId: string): Promise<void> {
  if (shouldSkipMerge(convId)) return;

  const response = await conversations.get(convId);
  const container = mergeContainerFor(convId);
  if (!container) return;

  const server = response.messages;
  const local = useStore.getState().getMessages(convId);
  // (The planner keeps its rendered messages out of the store, so this
  // never fires there - and the chat re-render would replace its view.)
  if (serverRewroteHistory(local, server) && !useStore.getState().isPlannerView) {
    log.info('External edit/delete in the open conversation - re-rendering', { conversationId: convId });
    await reloadCurrentConversation(convId);
    return;
  }

  reconcileUnfinished(convId, container, local, server);

  const localById = new Map(local.map((m) => [m.id, m]));
  const rendered = new Set(
    [...container.querySelectorAll<HTMLElement>('.message[data-message-id]')].map((el) => el.dataset.messageId)
  );
  const toRender = server.filter((m) => !localById.has(m.id) && !rendered.has(m.id));
  // A reply the other device is still generating (its empty placeholder is
  // filtered from messages - the server reports its id)
  const live = response.streaming_message_id;

  const wasAtBottom = isScrolledToBottom(container);
  for (const message of toRender) renderInServerOrder(convId, container, message, server);
  if (toRender.length > 0) {
    log.info('Merged messages from another device', { conversationId: convId, count: toRender.length });
    updateLatestAssistantMarker(container);
    lockOlderQuizBlocks(container);
    if (wasAtBottom) {
      programmaticScrollToBottom(container, true);
    } else {
      showNewMessagesPill();
    }
  }
  getSyncManager()?.markConversationRead(convId, response.message_pagination.total_count);
  // An agent conversation's new messages are now on screen: viewed (the
  // command-center unread badge stuck otherwise)
  if (toRender.length > 0) markAgentConversationViewed(response);

  if (live && !rendered.has(live)) void followRemoteStream(convId, live);
}

/**
 * Render a merged message where the server has it: before the first later
 * message already on screen (another device's question lands BEFORE the
 * steering this device sent into its turn), else at the end.
 */
function renderInServerOrder(convId: string, container: HTMLElement, message: Message, server: Message[]): void {
  const later = server.slice(server.indexOf(message) + 1);
  const before = later
    .map((m) => container.querySelector<HTMLElement>(`:scope > [data-message-id="${m.id}"]`))
    .find((el) => el !== null);
  useStore.getState().appendMessage(convId, message, before?.dataset.messageId);
  const lastBefore = container.lastElementChild;
  addMessageToUI(message, container, undefined, { animate: true });
  if (!before) return;
  // Move what the render appended (a bubble, or a row) into place
  const added: Element[] = [];
  for (let el = lastBefore ? lastBefore.nextElementSibling : container.firstElementChild; el; el = el.nextElementSibling) {
    added.push(el);
  }
  for (const el of added) container.insertBefore(el, before);
}
