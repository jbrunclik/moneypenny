/**
 * Actions on already-sent messages: regenerate / continue a response,
 * edit-and-resend, and retry / discard a failed send. Triggered by document
 * events from the message components (no component imports core logic).
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations, messages } from '../api/conversations';
import { ApiError } from '../api/http';
import { toast } from '../components/Toast';
import { addMessageToUI, hideLoadingIndicator, removeRenderedMessagesFrom } from '../components/messages';
import { beginInlineEdit } from '../components/messages/edit';
import { getElementById } from '../utils/dom';
import { getClientLocation } from '../utils/location';
import { removeOutboxEntry, restoreOutboxEntry } from './outbox';
import { resetAutoRetry } from './send-delivery';
import { sendStreamingMessage } from './stream-send';
import { sendBatchMessage } from './batch-send';
import { dispatchSend, sendUiMessage } from './messaging';
import { reopenResearchRun } from './deep-research';

const log = createLogger('messaging');

/**
 * Wire up retry/discard events dispatched by the failed-message affordance.
 * Called once from init.
 */
export function initOutboxHandlers(): void {
  document.addEventListener('outbox:retry', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    void retryFailedMessage(messageId);
  });
  document.addEventListener('outbox:discard', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    discardFailedMessage(messageId);
  });
  document.addEventListener('message:regenerate', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    void regenerateResponse(messageId);
  });
  document.addEventListener('message:continue', () => {
    void continueResponse();
  });
  // A reply that failed server-side (stream-send's error toast): answer the
  // user's message again
  document.addEventListener('message:retry-reply', answerLastUserMessage);
  // Steering the turn never read, now the chat's last message (steering.ts)
  document.addEventListener('message:answer-steering', answerLastUserMessage);

  document.addEventListener('message:edit', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    startMessageEdit(messageId);
  });
}

/** Reply to the conversation's last user message (a regenerate), when idle and on screen. */
function answerLastUserMessage(e: Event): void {
  const { convId } = (e as CustomEvent<{ convId: string }>).detail;
  if (useStore.getState().currentConversation?.id !== convId) return;
  if (useStore.getState().getActiveRequest(convId)) return;
  void reopenResearchRun(convId, 'retry').then((reopened) => {
    if (!reopened) void dispatchRerun(convId, 'regenerate');
  });
}

/**
 * The current conversation, when it is idle. Toasts and returns null while
 * a response in it is still running.
 */
function idleCurrentConversationId(): string | null {
  const convId = useStore.getState().currentConversation?.id;
  if (!convId) return null;
  if (useStore.getState().getActiveRequest(convId)) {
    toast.info('Please wait for the current response in this conversation to finish.');
    return null;
  }
  return convId;
}

/**
 * Re-run the agent on existing history (no new user message): regenerate
 * after deleting the last assistant response, or continue a truncated one.
 */
async function dispatchRerun(convId: string, mode: 'regenerate' | 'continue'): Promise<void> {
  // Anchor id keeps the send pipeline's bookkeeping happy - no optimistic
  // user bubble or outbox entry exists for reruns, so all the send-state
  // updates keyed on it are harmless no-ops
  const rerunAnchorId = `rerun-${Date.now()}`;
  const anonymousMode = useStore.getState().getAnonymousMode(convId);
  // Awaited inside the send, after its bubble is up (see dispatchSend)
  const clientLocation = getClientLocation();
  try {
    if (useStore.getState().streamingEnabled) {
      await sendStreamingMessage(convId, '', [], [], rerunAnchorId, anonymousMode, clientLocation, mode);
    } else {
      await sendBatchMessage(convId, '', [], [], rerunAnchorId, anonymousMode, clientLocation, mode);
    }
  } catch (error) {
    log.error('Rerun failed', { error, conversationId: convId, mode });
    hideLoadingIndicator();
    toast.error(error instanceof ApiError ? error.message : 'Failed to re-run the response.');
  }
}

async function regenerateResponse(messageId: string): Promise<void> {
  const convId = idleCurrentConversationId();
  if (!convId) return;
  // A deep-research run is re-offered, not re-run as an ordinary turn
  if (await reopenResearchRun(convId, 'regenerate')) return;
  log.info('Regenerating response', { conversationId: convId, messageId });
  try {
    await messages.delete(messageId);
  } catch (error) {
    log.error('Failed to delete response for regenerate', { error, messageId });
    toast.error('Failed to remove the previous response.');
    return;
  }
  useStore.getState().removeMessage(convId, messageId);
  document.querySelector(`.message[data-message-id="${messageId}"]`)?.remove();
  await dispatchRerun(convId, 'regenerate');
}

async function continueResponse(): Promise<void> {
  const convId = idleCurrentConversationId();
  if (!convId) return;
  if (await reopenResearchRun(convId, 'continue')) return;
  log.info('Continuing response', { conversationId: convId });
  await dispatchRerun(convId, 'continue');
}

/** Inline edit of a sent user message; saving truncates the tail and resends. */
function startMessageEdit(messageId: string): void {
  const convId = idleCurrentConversationId();
  if (!convId) return;
  const message = useStore.getState().getMessages(convId).find((m) => m.id === messageId);
  const messageEl = document.querySelector<HTMLElement>(`.message[data-message-id="${messageId}"]`);
  if (!message || !messageEl) return;
  // A message with attachments is edited in place (its files stay on the
  // server) and the reply regenerated: truncate-and-resend sent only the
  // text and the truncation deleted the files
  const hasFiles = Boolean(message.files && message.files.length > 0);
  beginInlineEdit(messageEl, message.content, {
    onSave: (newText) =>
      void (hasFiles ? submitAttachmentEdit(convId, messageId, newText) : submitMessageEdit(convId, messageId, newText)),
  });
}

async function submitAttachmentEdit(convId: string, messageId: string, newText: string): Promise<void> {
  const trimmed = newText.trim();
  if (!trimmed) return;
  log.info('Edit in place (attachments)', { conversationId: convId, messageId });
  try {
    await messages.edit(messageId, trimmed);
  } catch (error) {
    log.error('Failed to edit the message', { error, conversationId: convId, messageId });
    toast.error('Failed to edit the message.');
    return;
  }
  const store = useStore.getState();
  const list = store.getMessages(convId);
  const index = list.findIndex((m) => m.id === messageId);
  const edited = index >= 0 ? list[index] : undefined;
  // Drop the edited message and its tail from the screen, then put the
  // message back with the new text (its attachments render as before)
  store.truncateMessagesFrom(convId, messageId);
  removeRenderedMessagesFrom(messageId);
  if (edited) {
    const updated = { ...edited, content: trimmed };
    store.appendMessage(convId, updated);
    addMessageToUI(updated);
  }
  await dispatchRerun(convId, 'regenerate');
}

async function submitMessageEdit(convId: string, messageId: string, newText: string): Promise<void> {
  const trimmed = newText.trim();
  if (!trimmed) return;
  log.info('Edit-and-resend', { conversationId: convId, messageId });
  try {
    // Server first: the edited message and everything after it disappear
    await conversations.truncate(convId, messageId, true);
  } catch (error) {
    log.error('Failed to truncate for edit', { error, conversationId: convId, messageId });
    toast.error('Failed to edit the message.');
    return;
  }
  useStore.getState().truncateMessagesFrom(convId, messageId);
  // Remove the edited message and its tail from the DOM directly instead of
  // re-rendering the whole list from the store (cheaper, and keeps the
  // surviving bubbles' state - scroll position, loaded thumbnails)
  removeRenderedMessagesFrom(messageId);

  // Re-send through the normal pipeline (outbox, retry, streaming) - not
  // through the composer: that overwrote the user's draft there and sent
  // the files attached to it along with the edit
  if (await sendUiMessage(trimmed)) return;
  // Couldn't go now (blocked): keep the text where the user can send it
  const input = getElementById<HTMLTextAreaElement>('message-input');
  if (input && !input.value.trim()) {
    input.value = trimmed;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    toast.info('The edit could not be sent right now - it is in the message box.');
  } else {
    toast.error('The edit could not be sent right now. Please try again.');
  }
}

async function retryFailedMessage(messageId: string): Promise<void> {
  const convId = useStore.getState().currentConversation?.id;
  if (!convId) return;
  if (useStore.getState().getActiveRequest(convId)) {
    toast.info('Please wait for the current response in this conversation to finish.');
    return;
  }
  log.info('Retrying failed message', { conversationId: convId, messageId });
  await resendOutboxEntry(convId, messageId);
}

// UI-local (F2): messages this page is resending right now
const resending = new Set<string>();

/**
 * Send a failed outbox entry again (Retry, and the automatic resend on
 * reconnect in outbox-resend.ts). Resolves when the send settled.
 */
export async function resendOutboxEntry(convId: string, messageId: string): Promise<void> {
  // One resend per message at a time: a Retry tapped while the attachments
  // still load (no request registered yet), or another tab's resend at the
  // same moment (the server's duplicate check reads before it inserts)
  if (resending.has(messageId)) return;
  resending.add(messageId);
  try {
    await withMessageLock(messageId, () => resendNow(convId, messageId));
  } finally {
    resending.delete(messageId);
  }
}

/** Run `fn` holding this message's lock across tabs; skip it when another tab holds it. */
async function withMessageLock(messageId: string, fn: () => Promise<void>): Promise<void> {
  if (!('locks' in navigator) || !navigator.locks) return fn();
  await navigator.locks.request(`outbox-send:${messageId}`, { ifAvailable: true }, async (lock) => {
    if (lock) await fn();
  });
}

async function resendNow(convId: string, messageId: string): Promise<void> {
  // Attachments too big for localStorage come back from IndexedDB
  const entry = await restoreOutboxEntry(convId, messageId);
  if (!entry) return;
  // A resend earns a fresh automatic retry on transient failure
  resetAutoRetry(messageId);
  if (entry.filesDropped) {
    toast.warning('Attachments could not be restored after reload - sending text only.');
  }
  await dispatchSend(convId, entry);
}

function discardFailedMessage(messageId: string): void {
  const convId = useStore.getState().currentConversation?.id;
  if (!convId) return;
  log.info('Discarding failed message', { conversationId: convId, messageId });
  removeOutboxEntry(convId, messageId);
  useStore.getState().removeMessage(convId, messageId);
  document.querySelector(`.message[data-message-id="${messageId}"]`)?.remove();
}
