/**
 * Message sending entry point: validates and prepares a send from the
 * composer, renders the optimistic user message, and dispatches it to the
 * streaming (stream-send.ts) or batch (batch-send.ts) path - or, while the
 * conversation streams, to mid-run steering (steering.ts). Also owns the
 * dispatch-level failure handling.
 */

import { useStore } from '../state/store';
import { SEND_AUTO_RETRY_DELAY_MS } from '../config';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { ApiError } from '../api/http';
import { toast } from '../components/Toast';
import {
  renderConversationsList,
  setActiveConversation,
} from '../components/Sidebar';
import {
  addMessageToUI,
  hideLoadingIndicator,
  hasPendingApproval,
  loadAllRemainingNewerMessages,
  cleanupNewerMessagesScrollListener,
} from '../components/messages';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import {
  getMessageInput,
  clearMessageInput,
  refocusMessageInputAfterSend,
  setInputLoading,
  shouldAutoFocusInput,
} from '../components/MessageInput';
import { clearPendingFiles, getPendingFiles } from '../components/FileUpload';
import { stopVoiceRecording } from '../components/VoiceInput';
import { getElementById } from '../utils/dom';
import { programmaticScrollToBottom } from '../utils/thumbnails';
import { setConversationHash } from '../router/deeplink';
import type { Conversation, FileUpload, Message } from '../types/api';
import { setMessageSendState } from '../components/messages/send-state';

import { isTempConversation, createConversation } from './conversation';
import {
  addOutboxEntry,
  getOutboxEntry,
  markOutboxPending,
} from './outbox';
import { getClientLocation } from './location';
import { resetForceTools } from './toolbar';
import { claimAutoRetry, confirmDelivery, markSendFailed } from './send-delivery';
import { sendStreamingMessage } from './stream-send';
import { sendBatchMessage } from './batch-send';
import { interjectIntoActiveTurn } from './steering';
import { waitForReplyTo } from './reply-wait';

const log = createLogger('messaging');

type StoreState = ReturnType<typeof useStore.getState>;

/** A tracked outbox message, as handed to the streaming/batch send. */
interface SendEntry {
  id: string;
  content: string;
  files: FileUpload[];
  forceTools: string[];
  anonymousMode: boolean;
}

// ============ Composer hook ============

/**
 * Optional composer hook (quick actions): transforms the raw textarea text
 * into the outgoing message and is told when that message left the composer.
 * Registered by core/quick-actions.ts; messaging never imports it (no cycle).
 */
export interface ComposerHook {
  transform: (text: string) => string;
  onConsumed: () => void;
}

let composerHook: ComposerHook | null = null;

export function registerComposerHook(hook: ComposerHook | null): void {
  composerHook = hook;
}

// ============ Message Sending ============

/**
 * Whether the current conversation cannot take a new message right now
 * (planner still loading, or an agent approval pending). Toasts the reason.
 */
function isSendBlocked(store: StoreState): boolean {
  // If planner is still loading (placeholder conversation), block sending
  if (store.currentConversation?.id === 'planner-loading') {
    log.warn('Cannot send message while planner is loading');
    toast.info('Please wait for planner to finish loading...');
    return true;
  }

  // If there's a pending approval in this agent conversation, block sending
  // Only agent conversations can have pending approvals
  if (store.currentConversation?.is_agent && store.currentConversation.id) {
    const currentMessages = store.getMessages(store.currentConversation.id);
    if (currentMessages.length > 0 && hasPendingApproval(currentMessages)) {
      log.warn('Cannot send message while approval is pending', {
        conversationId: store.currentConversation.id,
        messageCount: currentMessages.length,
      });
      toast.warning('Please approve or reject the pending action before sending a new message.');
      return true;
    }
  }
  return false;
}

/** Auto-unarchive if sending a message in an archived conversation. */
async function unarchiveForSend(store: StoreState, conv: Conversation): Promise<Conversation> {
  if (!conv.archived || isTempConversation(conv.id)) return conv;
  try {
    await conversations.unarchive(conv.id);
    store.removeArchivedConversation(conv.id);
    // addConversation, not updateConversation: a deep-linked archived
    // conversation is never in store.conversations, so an update would
    // no-op and the conversation would vanish from the sidebar until the
    // next sync poll re-discovers it (addConversation merges if present)
    store.addConversation({ ...conv, archived: false });
    const unarchived = { ...conv, archived: false };
    store.setCurrentConversation(unarchived);
    renderConversationsList();
    log.info('Auto-unarchived conversation on message send', { conversationId: conv.id });
    return unarchived;
  } catch (error) {
    log.warn('Failed to auto-unarchive conversation', { error, conversationId: conv.id });
    // Continue sending - unarchive failure shouldn't block the message
    return conv;
  }
}

/**
 * If this is a temp conversation, persist it to the backend first.
 * Returns the persisted conversation, or null when that failed (toasted).
 */
async function persistTempConversation(store: StoreState, conv: Conversation): Promise<Conversation | null> {
  if (!isTempConversation(conv.id)) return conv;
  try {
    const persistedConv = await conversations.create(conv.model);
    const tempId = conv.id;

    // Migrate anonymous mode state from temp ID to persistent ID
    // This must happen BEFORE removing the temp conversation from store
    const wasAnonymous = store.getAnonymousMode(tempId);
    if (wasAnonymous) {
      store.setAnonymousMode(persistedConv.id, true);
    }
    store.migrateConversationDraft(tempId, persistedConv.id);

    // Update store with real ID
    store.removeConversation(tempId);
    store.addConversation(persistedConv);
    store.setCurrentConversation(persistedConv);
    renderConversationsList();
    setActiveConversation(persistedConv.id);

    // Update URL hash with the real (persisted) conversation ID
    // Use replaceState to replace the empty hash (from createConversation) with the real ID
    // This prevents empty hash entries from cluttering browser history
    setConversationHash(persistedConv.id, { replace: true });
    return persistedConv;
  } catch (error) {
    log.error('Failed to create conversation', { error });
    toast.error('Failed to create conversation. Please try again.');
    return null;
  }
}

/**
 * If we're in a partial view (e.g., after search navigation), load all remaining
 * newer messages first to ensure there's no gap when the new message is added.
 * This prevents the scenario where user searches, navigates to message 50, and sends
 * a new message which would appear after message 60 with a gap of 140 missing messages.
 * Returns false when loading failed (toasted).
 */
async function ensureFullHistoryLoaded(store: StoreState, convId: string): Promise<boolean> {
  const pagination = store.getMessagesPagination(convId);
  if (!pagination?.hasNewer) return true;
  log.info('In partial view, loading remaining messages before send', {
    conversationId: convId,
    hasNewer: pagination.hasNewer,
  });
  setInputLoading(true);
  try {
    await loadAllRemainingNewerMessages(convId);
    // Clean up the newer messages scroll listener since we've loaded everything
    cleanupNewerMessagesScrollListener();
    setInputLoading(false);
    return true;
  } catch (error) {
    log.error('Failed to load remaining messages before send', { error, conversationId: convId });
    setInputLoading(false);
    toast.error('Failed to load conversation history. Please try again.');
    return false;
  }
}

/**
 * Resolve the conversation to send into: unarchive it, persist a temp one,
 * and load any unloaded newer history. Returns null when the send must not
 * proceed.
 */
async function prepareConversationForSend(store: StoreState): Promise<Conversation | null> {
  let conv = store.currentConversation;
  if (!conv) return null;

  conv = await unarchiveForSend(store, conv);
  conv = await persistTempConversation(store, conv);
  if (!conv) return null;

  return (await ensureFullHistoryLoaded(store, conv.id)) ? conv : null;
}

/**
 * Create user message for UI. The ID is client-generated and travels to the
 * server as client_message_id, making retries idempotent (server dedupes).
 */
function buildOptimisticUserMessage(messageText: string, files: FileUpload[]): Message {
  return {
    id: crypto.randomUUID(),
    role: 'user',
    content: messageText,
    files: files.map((f, i) => ({
      name: f.name,
      type: f.type,
      fileIndex: i,
      previewUrl: f.previewUrl, // Include blob URL for immediate display
    })),
    created_at: new Date().toISOString(),
    status: 'pending',
  };
}

/** Add the user message to the UI immediately and scroll to show it. */
function renderOptimisticUserMessage(userMessage: Message): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;
  // Clear welcome message if present (first message in conversation)
  const welcomeMessage = messagesContainer.querySelector('.welcome-message');
  if (welcomeMessage) {
    welcomeMessage.remove();
  }
  addMessageToUI(userMessage, messagesContainer, undefined, { animate: true });
  // Scroll to bottom after adding user message so it's visible
  programmaticScrollToBottom(messagesContainer);
  // Update scroll button visibility after adding user message
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });
}

/**
 * Track, render and dispatch a new user message in a prepared conversation.
 */
async function sendNewMessage(
  conv: Conversation,
  messageText: string,
  files: FileUpload[],
  forceTools: string[]
): Promise<void> {
  const userMessage = buildOptimisticUserMessage(messageText, files);

  // Use fresh store reference to get anonymous mode (not a stale snapshot from before)
  // This is critical because the conversation ID may have changed from temp-xxx to a real ID
  const anonymousMode = useStore.getState().getAnonymousMode(conv.id);

  // Track in store + outbox before any network I/O: a send that dies with the
  // page resurfaces as a failed message instead of silently disappearing
  useStore.getState().appendMessage(conv.id, userMessage);
  addOutboxEntry({
    id: userMessage.id,
    conversationId: conv.id,
    content: messageText,
    files,
    forceTools,
    anonymousMode,
    createdAt: userMessage.created_at,
  });

  // Optimistically bump the sidebar entry so the conversation moves to the
  // top ("Today") with the new preview immediately, instead of staying in
  // its old date group until the next sync poll returns the server timestamp
  useStore.getState().bumpConversationActivity(conv.id, messageText);
  renderConversationsList();

  renderOptimisticUserMessage(userMessage);

  // Clear input, draft and force tools (one-shot)
  clearMessageInput();
  composerHook?.onConsumed();
  clearPendingFiles();
  useStore.getState().setConversationDraft(conv.id, '');
  resetForceTools();

  await dispatchSend(conv.id, {
    id: userMessage.id,
    content: messageText,
    files,
    forceTools,
    anonymousMode,
  });
}

/**
 * Send a message.
 */
export async function sendMessage(): Promise<void> {
  // Stop voice recording if active (prevents text from being re-added after send)
  stopVoiceRecording();

  let store = useStore.getState();
  const rawText = getMessageInput();
  const messageText = composerHook ? composerHook.transform(rawText) : rawText;
  const files = getPendingFiles();

  if (!messageText && files.length === 0) return;

  log.info('Sending message', {
    conversationId: store.currentConversation?.id,
    messageLength: messageText.length,
    fileCount: files.length,
    streaming: store.streamingEnabled,
  });

  if (isSendBlocked(store)) return;

  // Create local conversation if none selected
  if (!store.currentConversation) {
    createConversation();
    store = useStore.getState();
  }
  const forceTools = [...store.forceTools];

  const conv = await prepareConversationForSend(store);
  if (!conv) return;

  // Sending while THIS conversation streams = mid-run steering: the text is
  // injected into the running turn between tool rounds (and persisted to
  // history) instead of queueing a new turn. Attachments can't steer - keep
  // the old blocking behavior for them. Must run BEFORE the optimistic
  // render: a bubble with no request behind it looks sent but never was.
  const activeRequest = useStore.getState().getActiveRequest(conv.id);
  if (activeRequest) {
    // Steering a turn that is ending would save a message nobody answers
    if (activeRequest.stopping) {
      toast.info('The response is stopping - send again in a moment.');
      return;
    }
    if (files.length > 0) {
      toast.info('Please wait for the current response before sending attachments.');
      return;
    }
    await interjectIntoActiveTurn(conv.id, messageText);
    return;
  }

  await sendNewMessage(conv, messageText, files, forceTools);
}

/**
 * Run the actual send (streaming or batch) for a tracked outbox message.
 * Shared by the initial send and by retries of failed messages.
 */
export async function dispatchSend(convId: string, entry: SendEntry): Promise<void> {
  markOutboxPending(convId, entry.id);
  useStore.getState().updateMessage(convId, entry.id, { status: 'pending' });
  setMessageSendState(entry.id, 'pending');

  // Device location (null when sharing is disabled, denied, or times out)
  const clientLocation = await getClientLocation();

  try {
    if (useStore.getState().streamingEnabled) {
      await sendStreamingMessage(convId, entry.content, entry.files, entry.forceTools, entry.id, entry.anonymousMode, clientLocation);
    } else {
      await sendBatchMessage(convId, entry.content, entry.files, entry.forceTools, entry.id, entry.anonymousMode, clientLocation);
    }
    // Note: incrementLocalMessageCount is handled inside sendStreamingMessage (in finally block)
    // and sendBatchMessage (after success) to avoid race conditions with sync
  } catch (error) {
    await handleSendFailure(convId, entry.id, error);
  } finally {
    if (shouldAutoFocusInput()) {
      refocusMessageInputAfterSend();
    }
  }
}

function toastSendError(error: unknown): void {
  if (error instanceof ApiError) {
    if (error.isTimeout) {
      toast.error('Request timed out. Use Retry on the message to send it again.');
    } else if (error.isNetworkError) {
      toast.error('Network error. Please check your connection.');
    } else {
      toast.error(error.message || 'Failed to send message.');
    }
  } else {
    toast.error('An unexpected error occurred. Please try again.');
  }
}

/**
 * Handle a send failure surfaced to the dispatch level: reconcile 409s
 * (the original request actually landed), mark real failures, toast.
 */
async function handleSendFailure(convId: string, messageId: string, error: unknown): Promise<void> {
  log.error('Failed to send message', { error, conversationId: convId, messageId });

  // 409 CONFLICT: a previous attempt already delivered this message, and its
  // turn may still be running. Confirm locally and keep the spinner up until
  // the reply appears.
  if (error instanceof ApiError && error.status === 409) {
    log.info('Send already delivered (409), reconciling', { conversationId: convId, messageId });
    confirmDelivery(convId, messageId);
    await waitForReplyTo(convId, messageId);
    hideLoadingIndicator();
    return;
  }
  hideLoadingIndicator();

  if (error instanceof Error && error.name === 'AbortError') {
    markSendFailed(convId, messageId);
    toast.warning('Request was cancelled.');
    return;
  }

  // Transient failures (network drop, connect timeout) get one automatic
  // retry before surfacing - idempotent thanks to the client message ID.
  // The message stays visually PENDING during the wait (no retry/discard
  // buttons yet); the toast tells the user what's happening.
  const isTransient = error instanceof ApiError && (error.isNetworkError || error.isTimeout);
  if (isTransient && claimAutoRetry(messageId)) {
    log.info('Auto-retrying send after transient failure', { conversationId: convId, messageId });
    toast.info('Connection problem - retrying...');
    await new Promise((resolve) => setTimeout(resolve, SEND_AUTO_RETRY_DELAY_MS));
    const entry = getOutboxEntry(convId, messageId);
    if (entry) {
      await dispatchSend(convId, entry);
      return;
    }
  }

  markSendFailed(convId, messageId);
  toastSendError(error);
}
