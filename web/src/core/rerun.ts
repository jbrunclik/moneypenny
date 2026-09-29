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
import { hideLoadingIndicator, removeRenderedMessagesFrom } from '../components/messages';
import { beginInlineEdit } from '../components/messages/edit';
import { getElementById } from '../utils/dom';
import { getClientLocation } from './location';
import { getOutboxEntry, removeOutboxEntry } from './outbox';
import { resetAutoRetry } from './send-delivery';
import { sendStreamingMessage } from './stream-send';
import { sendBatchMessage } from './batch-send';
import { dispatchSend, sendMessage } from './messaging';

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
  document.addEventListener('message:edit', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    startMessageEdit(messageId);
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
  const clientLocation = await getClientLocation();
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
  beginInlineEdit(messageEl, message.content, {
    onSave: (newText) => void submitMessageEdit(convId, messageId, newText),
  });
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

  // Re-send through the normal pipeline (outbox, retry, streaming) by
  // placing the edited text in the composer and sending
  const input = getElementById<HTMLTextAreaElement>('message-input');
  if (input) {
    input.value = trimmed;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  await sendMessage();
}

async function retryFailedMessage(messageId: string): Promise<void> {
  const convId = useStore.getState().currentConversation?.id;
  if (!convId) return;
  const entry = getOutboxEntry(convId, messageId);
  if (!entry) return;
  if (useStore.getState().getActiveRequest(convId)) {
    toast.info('Please wait for the current response in this conversation to finish.');
    return;
  }
  log.info('Retrying failed message', { conversationId: convId, messageId });
  // A manual retry earns a fresh automatic retry on transient failure
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
