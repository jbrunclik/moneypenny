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
import type { Conversation, Message } from '../types/api';
import { getElementById, isScrolledToBottom } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { programmaticScrollToBottom } from '../utils/thumbnails';
import { isTempConversation } from './conversation';
import { readInflightStream } from './inflight-streams';
import { followRemoteStream } from './stream-resume';
import { reloadCurrentConversation } from './sync-banner';

const log = createLogger('remote-merge');

// One merge at a time; a request during one runs again after it
let inFlight: Promise<void> | null = null;
let rerun = false;

/** Merge the open conversation's external changes (serialized). */
export function mergeExternalChanges(convId: string): Promise<void> {
  if (inFlight) {
    rerun = true;
    return inFlight;
  }
  inFlight = (async () => {
    do {
      rerun = false;
      await mergeOnce(convId);
    } while (rerun);
  })()
    .catch((error: unknown) => {
      log.warn('Merging external changes failed', { error, conversationId: convId });
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/** Messages only this device has (not yet on the server). */
function isLocalOnly(message: Message): boolean {
  return message.status === 'pending' || message.status === 'failed';
}

async function mergeOnce(convId: string): Promise<void> {
  const store = useStore.getState();
  if (isTempConversation(convId) || store.currentConversation?.id !== convId) return;
  // Our own turn running here: its end applies the deferred change
  if (store.getActiveRequest(convId)) return;
  // Viewing an older window (search jump): newer pages load on scroll
  if (store.messagesPagination.get(convId)?.hasNewer) return;

  const response = await conversations.get(convId);
  const container = getElementById<HTMLDivElement>('messages');
  if (!container || useStore.getState().currentConversation?.id !== convId) return;
  if (useStore.getState().getActiveRequest(convId)) return;

  const server = response.messages;
  const local = useStore.getState().getMessages(convId);
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
  // (The planner keeps its rendered messages out of the store, so this
  // never fires there - and the chat re-render would replace its view.)
  if ((vanished || edited) && !useStore.getState().isPlannerView) {
    log.info('External edit/delete in the open conversation - re-rendering', { conversationId: convId });
    await reloadCurrentConversation(convId);
    return;
  }

  const rendered = new Set(
    [...container.querySelectorAll<HTMLElement>('.message[data-message-id]')].map((el) => el.dataset.messageId)
  );
  const toRender = server.filter((m) => !localById.has(m.id) && !rendered.has(m.id));
  // A reply the other device is still generating (its empty placeholder is
  // filtered from messages - the server reports its id)
  const live = response.streaming_message_id;

  const wasAtBottom = isScrolledToBottom(container);
  for (const message of toRender) {
    useStore.getState().appendMessage(convId, message);
    addMessageToUI(message, container, undefined, { animate: true });
  }
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

  if (live && !rendered.has(live)) void followRemoteStream(convId, live);
}

/**
 * Opening a conversation another device is streaming into: follow its reply
 * live (the server reports it - the empty placeholder itself is filtered
 * from responses), unless this device owns that turn (a reload resumes it
 * via resumeInflightStreamIfAny).
 */
export function followRemoteStreamOnOpen(conv: Conversation): void {
  if (!conv.streaming_message_id || readInflightStream(conv.id)) return;
  void followRemoteStream(conv.id, conv.streaming_message_id);
}
