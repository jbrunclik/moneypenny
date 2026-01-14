/**
 * Message sending module.
 * Handles message sending, streaming, batch mode, and request management.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations, chat, ApiError } from '../api/client';
import { toast } from '../components/Toast';
import {
  renderConversationsList,
  setActiveConversation,
} from '../components/Sidebar';
import {
  addMessageToUI,
  addStreamingMessage,
  updateStreamingMessage,
  finalizeStreamingMessage,
  updateStreamingThinking,
  updateStreamingToolStart,
  updateStreamingToolDetail,
  updateStreamingToolEnd,
  cleanupStreamingContext,
  getStreamingMessageElement,
  showLoadingIndicator,
  hideLoadingIndicator,
  updateUserMessageId,
  loadAllRemainingNewerMessages,
  cleanupNewerMessagesScrollListener,
} from '../components/messages';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import {
  getMessageInput,
  clearMessageInput,
  focusMessageInput,
  setInputLoading,
  shouldAutoFocusInput,
  showUploadProgress,
  hideUploadProgress,
  updateUploadProgress,
} from '../components/MessageInput';
import { clearPendingFiles, getPendingFiles } from '../components/FileUpload';
import { stopVoiceRecording } from '../components/VoiceInput';
import { getElementById, isScrolledToBottom } from '../utils/dom';
import { enableScrollOnImageLoad, getThumbnailObserver, observeThumbnail, programmaticScrollToBottom } from '../utils/thumbnails';
import { setConversationHash } from '../router/deeplink';
import type { Message, ThinkingState, ToolMetadata, ThinkingTraceItem, Source, GeneratedImage, FileMetadata } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';

import { isTempConversation, createConversation, updateConversationTitle } from './conversation';
import { updateConversationCost, resetForceTools } from './toolbar';

const log = createLogger('messaging');

// ============ Active Request Management ============

// Track active requests per conversation to allow continuation when switching
interface ActiveRequest {
  conversationId: string;
  type: 'stream' | 'batch';
  abortController?: AbortController;
}

const activeRequests = new Map<string, ActiveRequest>();

/**
 * Abort a streaming request for a conversation.
 * Called when user clicks the stop button.
 * Returns true if a request was found and aborted.
 */
export function abortStreamingRequest(convId: string): boolean {
  for (const [requestId, request] of activeRequests.entries()) {
    if (request.conversationId === convId && request.type === 'stream' && request.abortController) {
      log.info('Aborting streaming request', { conversationId: convId, requestId });
      request.abortController.abort();
      return true;
    }
  }
  return false;
}

/**
 * Handle stop button click - abort current streaming request.
 * This is passed to MessageInput as the onStop callback.
 */
export function handleStopStreaming(): void {
  const currentConvId = useStore.getState().currentConversation?.id;
  if (currentConvId) {
    const aborted = abortStreamingRequest(currentConvId);
    if (!aborted) {
      log.warn('No streaming request found to abort', { conversationId: currentConvId });
    }
  }
}

// ============ Thinking State Management ============

/**
 * Deep copy a ThinkingState to avoid reference issues when storing in Zustand.
 */
function deepCopyThinkingState(state: ThinkingState): ThinkingState {
  return {
    isThinking: state.isThinking,
    thinkingText: state.thinkingText,
    activeTool: state.activeTool,
    activeToolDetail: state.activeToolDetail,
    completedTools: [...state.completedTools],
    trace: state.trace.map(item => ({
      type: item.type,
      label: item.label,
      detail: item.detail,
      completed: item.completed,
    })),
  };
}

/**
 * Update local thinking state based on streaming event type.
 * This mirrors the logic in ThinkingIndicator.ts but operates on a local state object
 * so we can track state even when the user switches conversations.
 */
function updateLocalThinkingState(
  state: ThinkingState,
  eventType: 'thinking' | 'tool_start' | 'tool_detail' | 'tool_end',
  toolOrText?: string,
  detail?: string,
  metadata?: ToolMetadata
): void {
  if (eventType === 'thinking') {
    // Find existing thinking item or create one
    const thinkingItem = state.trace.find(item => item.type === 'thinking');
    if (thinkingItem) {
      thinkingItem.detail = toolOrText;
      thinkingItem.completed = false;
    } else {
      state.trace.push({
        type: 'thinking',
        label: 'thinking',
        detail: toolOrText,
        completed: false,
      });
    }
    state.thinkingText = toolOrText || '';
    state.isThinking = true;
  } else if (eventType === 'tool_detail') {
    // Update detail for an existing tool
    const toolItem = state.trace.find(
      item => item.type === 'tool' && item.label === toolOrText && !item.completed
    );
    if (toolItem) {
      toolItem.detail = detail;
    }
    if (state.activeTool === toolOrText) {
      state.activeToolDetail = detail;
    }
  } else if (eventType === 'tool_start') {
    // Mark thinking as completed
    const thinkingIndex = state.trace.findIndex(item => item.type === 'thinking');
    if (thinkingIndex !== -1) {
      state.trace[thinkingIndex].completed = true;
    }
    // Create tool item and insert before thinking (to keep thinking at end)
    const toolItem: ThinkingTraceItem = {
      type: 'tool',
      label: toolOrText || '',
      detail,
      completed: false,
      metadata, // Include metadata from backend for display
    };
    if (thinkingIndex !== -1) {
      state.trace.splice(thinkingIndex, 0, toolItem);
    } else {
      state.trace.push(toolItem);
    }
    state.activeTool = toolOrText || null;
    state.activeToolDetail = detail;
    state.isThinking = false;
  } else if (eventType === 'tool_end') {
    // Find the tool and mark it completed
    for (const item of state.trace) {
      if (item.type === 'tool' && item.label === toolOrText && !item.completed) {
        item.completed = true;
        break;
      }
    }
    if (toolOrText && !state.completedTools.includes(toolOrText)) {
      state.completedTools.push(toolOrText);
    }
    if (state.activeTool === toolOrText) {
      state.activeTool = null;
      state.activeToolDetail = undefined;
    }
  }
}

// ============ Message Sending ============

/**
 * Send a message.
 */
export async function sendMessage(): Promise<void> {
  // Stop voice recording if active (prevents text from being re-added after send)
  stopVoiceRecording();

  let store = useStore.getState();
  const messageText = getMessageInput();
  const files = getPendingFiles();

  if (!messageText && files.length === 0) return;

  log.info('Sending message', {
    conversationId: store.currentConversation?.id,
    messageLength: messageText.length,
    fileCount: files.length,
    streaming: store.streamingEnabled,
  });

  // If planner is still loading (placeholder conversation), block sending
  if (store.currentConversation?.id === 'planner-loading') {
    log.warn('Cannot send message while planner is loading');
    toast.info('Please wait for planner to finish loading...');
    return;
  }

  // Create local conversation if none selected
  if (!store.currentConversation) {
    createConversation();
    store = useStore.getState();
  }

  let conv = store.currentConversation;
  if (!conv) return;

  // If this is a temp conversation, persist it to the backend first
  if (isTempConversation(conv.id)) {
    try {
      const persistedConv = await conversations.create(conv.model);
      const tempId = conv.id;

      // Migrate anonymous mode state from temp ID to persistent ID
      // This must happen BEFORE removing the temp conversation from store
      const wasAnonymous = store.getAnonymousMode(tempId);
      if (wasAnonymous) {
        store.setAnonymousMode(persistedConv.id, true);
      }

      // Update store with real ID
      store.removeConversation(tempId);
      store.addConversation(persistedConv);
      store.setCurrentConversation(persistedConv);
      renderConversationsList();
      setActiveConversation(persistedConv.id);
      conv = persistedConv;

      // Update URL hash with the real (persisted) conversation ID
      // Use replaceState to replace the empty hash (from createConversation) with the real ID
      // This prevents empty hash entries from cluttering browser history
      setConversationHash(persistedConv.id, { replace: true });
    } catch (error) {
      log.error('Failed to create conversation', { error });
      toast.error('Failed to create conversation. Please try again.');
      return;
    }
  }

  // If we're in a partial view (e.g., after search navigation), load all remaining
  // newer messages first to ensure there's no gap when the new message is added.
  // This prevents the scenario where user searches, navigates to message 50, and sends
  // a new message which would appear after message 60 with a gap of 140 missing messages.
  const pagination = store.getMessagesPagination(conv.id);
  if (pagination?.hasNewer) {
    log.info('In partial view, loading remaining messages before send', {
      conversationId: conv.id,
      hasNewer: pagination.hasNewer,
    });
    setInputLoading(true);
    try {
      await loadAllRemainingNewerMessages(conv.id);
      // Clean up the newer messages scroll listener since we've loaded everything
      cleanupNewerMessagesScrollListener();
    } catch (error) {
      log.error('Failed to load remaining messages before send', { error, conversationId: conv.id });
      setInputLoading(false);
      toast.error('Failed to load conversation history. Please try again.');
      return;
    }
  }

  // Create user message for UI
  const userMessage: Message = {
    id: `temp-${Date.now()}`,
    role: 'user',
    content: messageText,
    files: files.map((f, i) => ({
      name: f.name,
      type: f.type,
      fileIndex: i,
      previewUrl: f.previewUrl, // Include blob URL for immediate display
    })),
    created_at: new Date().toISOString(),
  };

  // Add to UI immediately and scroll to bottom to show user's message
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    // Clear welcome message if present (first message in conversation)
    const welcomeMessage = messagesContainer.querySelector('.welcome-message');
    if (welcomeMessage) {
      welcomeMessage.remove();
    }
    addMessageToUI(userMessage, messagesContainer);
    // Scroll to bottom after adding user message so it's visible
    programmaticScrollToBottom(messagesContainer);
    // Update scroll button visibility after adding user message
    requestAnimationFrame(() => {
      checkScrollButtonVisibility();
    });
  }

  // Clear input and reset force tools (one-shot)
  clearMessageInput();
  clearPendingFiles();
  setInputLoading(true);
  const forceTools = [...store.forceTools];
  // Use fresh store reference to get anonymous mode (not the stale `store` from the beginning)
  // This is critical because the conversation ID may have changed from temp-xxx to a real ID
  const anonymousMode = useStore.getState().getAnonymousMode(conv.id);
  resetForceTools();

  try {
    if (store.streamingEnabled) {
      await sendStreamingMessage(conv.id, messageText, files, forceTools, userMessage.id, anonymousMode);
    } else {
      await sendBatchMessage(conv.id, messageText, files, forceTools, userMessage.id, anonymousMode);
    }
    // Clear draft on successful send
    useStore.getState().clearDraft();

    // Note: incrementLocalMessageCount is handled inside sendStreamingMessage (in finally block)
    // and sendBatchMessage (after success) to avoid race conditions with sync
  } catch (error) {
    log.error('Failed to send message', { error, conversationId: conv.id });
    hideLoadingIndicator();

    // Save draft for recovery
    useStore.getState().setDraft(messageText, files);

    // Show appropriate error toast
    if (error instanceof ApiError) {
      if (error.isTimeout) {
        toast.error('Request timed out. Your message has been saved.', {
          action: { label: 'Retry', onClick: () => retryFromDraft() },
        });
      } else if (error.isNetworkError) {
        toast.error('Network error. Please check your connection.', {
          action: { label: 'Retry', onClick: () => retryFromDraft() },
        });
      } else if (error.retryable) {
        toast.error('Failed to send message. Please try again.', {
          action: { label: 'Retry', onClick: () => retryFromDraft() },
        });
      } else {
        toast.error(error.message || 'Failed to send message.');
      }
    } else if (error instanceof Error && error.name === 'AbortError') {
      toast.warning('Request was cancelled.');
    } else {
      toast.error('An unexpected error occurred. Please try again.');
    }
  } finally {
    setInputLoading(false);
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}

/**
 * Retry sending message from saved draft.
 */
function retryFromDraft(): void {
  const { draftMessage, draftFiles } = useStore.getState();
  if (draftMessage || draftFiles.length > 0) {
    // Restore draft to input
    const textarea = getElementById<HTMLTextAreaElement>('message-input');
    if (textarea && draftMessage) {
      textarea.value = draftMessage;
      // Trigger input event to update UI
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }
    // Restore files to pending files
    draftFiles.forEach((file) => {
      useStore.getState().addPendingFile(file);
    });
    // Clear draft after restoring
    useStore.getState().clearDraft();
    // Focus input - user explicitly clicked retry, so it's intentional even on iOS
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}

// ============ Streaming Message ============

/**
 * State for a streaming request, encapsulating all mutable data.
 */
interface StreamingState {
  messageEl: HTMLElement;
  fullContent: string;
  thinkingState: ThinkingState;
  messageSuccessful: boolean;
  uploadProgressHidden: boolean;
}

/**
 * Initialize streaming request state and tracking.
 */
function initStreamingRequest(
  convId: string,
  hasFiles: boolean
): { state: StreamingState; requestId: string; abortController: AbortController } {
  const messageEl = addStreamingMessage(convId);
  const requestId = `stream-${convId}-${Date.now()}`;
  const abortController = new AbortController();

  // Track request
  activeRequests.set(requestId, {
    conversationId: convId,
    type: 'stream',
    abortController,
  });

  // Register in store for UI restoration
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'stream',
    content: '',
    thinkingState: undefined,
  });

  // Mark streaming state
  getSyncManager()?.setConversationStreaming(convId, true);
  useStore.getState().setStreamingConversation(convId);

  // Show upload progress if needed
  if (hasFiles) {
    showUploadProgress();
    updateUploadProgress(0);
    const progressText = document.querySelector('.upload-progress-text');
    if (progressText) {
      progressText.textContent = 'Uploading...';
    }
  }

  const state: StreamingState = {
    messageEl,
    fullContent: '',
    thinkingState: {
      isThinking: true,
      thinkingText: '',
      activeTool: null,
      activeToolDetail: undefined,
      completedTools: [],
      trace: [],
    },
    messageSuccessful: false,
    uploadProgressHidden: false,
  };

  return { state, requestId, abortController };
}

/**
 * Clean up streaming request resources.
 */
function cleanupStreamingRequest(
  requestId: string,
  convId: string,
  messageSuccessful: boolean
): void {
  activeRequests.delete(requestId);
  cleanupStreamingContext();
  useStore.getState().removeActiveRequest(convId);

  hideUploadProgress();
  useStore.getState().setUploadProgress(null);

  if (messageSuccessful) {
    getSyncManager()?.incrementLocalMessageCount(convId, 2);
  }

  getSyncManager()?.setConversationStreaming(convId, false);
  useStore.getState().setStreamingConversation(null);
}

/**
 * Handle scroll-to-bottom for lazy-loaded images after message completion.
 */
function handleImageScrollAfterMessage(
  messageEl: HTMLElement,
  files: Array<{ type: string; previewUrl?: string }> | undefined
): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer || !files) return;

  const hasImagesToLoad = files.some((f) => f.type.startsWith('image/') && !f.previewUrl);
  const wasAtBottom = isScrolledToBottom(messagesContainer);

  if (hasImagesToLoad && wasAtBottom) {
    enableScrollOnImageLoad();
    programmaticScrollToBottom(messagesContainer, false);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        triggerVisibleImageObservation(messageEl, messagesContainer);
        checkScrollButtonVisibility();
      });
    });
  } else {
    if (wasAtBottom) {
      programmaticScrollToBottom(messagesContainer);
    }
    requestAnimationFrame(() => {
      checkScrollButtonVisibility();
    });
  }
}

/**
 * Trigger observation for visible images that haven't started loading.
 */
function triggerVisibleImageObservation(
  messageEl: HTMLElement,
  container: HTMLElement
): void {
  const images = messageEl.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]:not([src])'
  );
  const containerRect = container.getBoundingClientRect();

  images.forEach((img) => {
    const rect = img.getBoundingClientRect();
    const isVisible = rect.top < containerRect.bottom && rect.bottom > containerRect.top;
    if (isVisible && !img.src) {
      getThumbnailObserver().unobserve(img);
      observeThumbnail(img);
    }
  });
}

/**
 * Process a single streaming event and update state/UI.
 */
function processStreamEvent(
  event: { type: string; [key: string]: unknown },
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): { shouldBreak?: boolean; error?: Error } {
  const store = useStore.getState();
  const isCurrentConversation = store.currentConversation?.id === convId;

  // Update message element reference (may have been restored after conversation switch)
  const currentMessageEl = getStreamingMessageElement(convId);
  if (currentMessageEl) {
    state.messageEl = currentMessageEl;
  }

  switch (event.type) {
    case 'user_message_saved':
      if (event.user_message_id) {
        updateUserMessageId(tempUserMessageId, event.user_message_id as string);
      }
      break;

    case 'thinking':
      updateLocalThinkingState(state.thinkingState, 'thinking', event.text as string);
      if (isCurrentConversation) {
        updateStreamingThinking(event.text as string);
      }
      store.updateActiveRequestContent(convId, state.fullContent, deepCopyThinkingState(state.thinkingState));
      break;

    case 'tool_start':
      updateLocalThinkingState(
        state.thinkingState,
        'tool_start',
        event.tool as string,
        event.detail as string | undefined,
        event.metadata as ToolMetadata | undefined
      );
      if (isCurrentConversation) {
        updateStreamingToolStart(
          event.tool as string,
          event.detail as string | undefined,
          event.metadata as ToolMetadata | undefined
        );
      }
      store.updateActiveRequestContent(convId, state.fullContent, deepCopyThinkingState(state.thinkingState));
      break;

    case 'tool_detail':
      updateLocalThinkingState(
        state.thinkingState,
        'tool_detail',
        event.tool as string,
        event.detail as string | undefined
      );
      if (isCurrentConversation && event.detail) {
        updateStreamingToolDetail(event.tool as string, event.detail as string);
      }
      store.updateActiveRequestContent(convId, state.fullContent, deepCopyThinkingState(state.thinkingState));
      break;

    case 'tool_end':
      updateLocalThinkingState(state.thinkingState, 'tool_end', event.tool as string);
      if (isCurrentConversation) {
        updateStreamingToolEnd(event.tool as string);
      }
      store.updateActiveRequestContent(convId, state.fullContent, deepCopyThinkingState(state.thinkingState));
      break;

    case 'token':
      state.fullContent += event.text as string;
      if (state.thinkingState.isThinking) {
        state.thinkingState.isThinking = false;
      }
      store.updateActiveRequestContent(convId, state.fullContent, deepCopyThinkingState(state.thinkingState));
      if (isCurrentConversation) {
        updateStreamingMessage(state.messageEl, state.fullContent);
      }
      break;

    case 'error':
      return handleStreamError(event, state);
  }

  return {};
}

/**
 * Handle stream error event.
 */
function handleStreamError(
  event: { type: string; message?: string; code?: string; retryable?: boolean },
  state: StreamingState
): { error: Error } {
  log.error('Stream error', { message: event.message });

  if (state.fullContent.trim()) {
    state.messageEl.classList.add('message-incomplete');
  } else {
    state.messageEl.remove();
  }

  const streamError = new ApiError(
    event.message || 'Failed to generate response.',
    event.code === 'TIMEOUT' ? 408 : 500,
    {
      code: event.code,
      retryable: event.retryable ?? false,
      isTimeout: event.code === 'TIMEOUT',
    }
  );

  return { error: streamError };
}

/**
 * Handle stream done event.
 */
async function handleStreamDone(
  event: {
    id: string;
    created_at: string;
    user_message_id?: string;
    sources?: Source[];
    generated_images?: GeneratedImage[];
    files?: FileMetadata[];
    title?: string;
    language?: string;
  },
  state: StreamingState,
  convId: string,
  tempUserMessageId: string
): Promise<void> {
  log.info('Streaming complete', { conversationId: convId, messageId: event.id });

  if (event.user_message_id) {
    updateUserMessageId(tempUserMessageId, event.user_message_id);
  }

  const isCurrentConversation = useStore.getState().currentConversation?.id === convId;
  if (!isCurrentConversation) return;

  finalizeStreamingMessage(
    state.messageEl,
    event.id,
    event.created_at,
    event.sources,
    event.generated_images,
    event.files,
    'assistant',
    event.language
  );

  handleImageScrollAfterMessage(state.messageEl, event.files);
  updateConversationTitle(convId, event.title);
  await updateConversationCost(convId);

  state.messageSuccessful = true;
}

/**
 * Send message with streaming response.
 */
async function sendStreamingMessage(
  convId: string,
  message: string,
  files: ReturnType<typeof getPendingFiles>,
  forceTools: string[],
  tempUserMessageId: string,
  anonymousMode: boolean
): Promise<void> {
  const hasFiles = files && files.length > 0;
  const { state, requestId, abortController } = initStreamingRequest(convId, hasFiles);

  try {
    for await (const event of chat.stream(convId, message, files, forceTools, abortController, anonymousMode)) {
      // Hide upload progress on first event
      if (hasFiles && !state.uploadProgressHidden) {
        hideUploadProgress();
        useStore.getState().setUploadProgress(null);
        state.uploadProgressHidden = true;
      }

      // Handle done event specially (async)
      if (event.type === 'done') {
        await handleStreamDone(event as Parameters<typeof handleStreamDone>[0], state, convId, tempUserMessageId);
        continue;
      }

      // Process other events
      const result = processStreamEvent(event, state, convId, tempUserMessageId);
      if (result.error) {
        throw result.error;
      }
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      log.info('Stream aborted by user', { conversationId: convId });
      state.messageEl.remove();
      toast.info('Response stopped.');
      return;
    }

    log.error('Streaming failed', { error, conversationId: convId });

    if (state.fullContent.trim()) {
      state.messageEl.classList.add('message-incomplete');
    } else {
      state.messageEl.remove();
    }

    const isCurrentConversation = useStore.getState().currentConversation?.id === convId;
    if (isCurrentConversation) {
      throw error;
    }
  } finally {
    cleanupStreamingRequest(requestId, convId, state.messageSuccessful);
  }
}

// ============ Batch Message ============

/**
 * Send message with batch response.
 */
async function sendBatchMessage(
  convId: string,
  message: string,
  files: ReturnType<typeof getPendingFiles>,
  forceTools: string[],
  tempUserMessageId: string,
  anonymousMode: boolean
): Promise<void> {
  const requestId = `batch-${convId}-${Date.now()}`;

  // Track this request
  const request: ActiveRequest = {
    conversationId: convId,
    type: 'batch',
  };
  activeRequests.set(requestId, request);

  // Register active request in store for UI restoration on conversation switch
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'batch',
  });

  // Show upload progress for requests with files
  const hasFiles = files && files.length > 0;
  if (hasFiles) {
    showUploadProgress();
  } else {
    showLoadingIndicator();
  }

  try {
    // Pass progress callback for requests with files
    const onUploadProgress = hasFiles ? (progress: number) => {
      updateUploadProgress(progress);
      useStore.getState().setUploadProgress(progress);
    } : undefined;

    const response = await chat.sendBatch(convId, message, files, forceTools, onUploadProgress, anonymousMode);
    log.info('Batch response received', { conversationId: convId, messageId: response.id });

    // Update user message ID from temp to real ID (for file fetching in lightbox)
    if (response.user_message_id) {
      updateUserMessageId(tempUserMessageId, response.user_message_id);
    }

    // Check if conversation is still current before updating UI
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    if (!isCurrentConversation) {
      // User switched conversations - message is saved to DB, just hide loading
      hideLoadingIndicator();
      hideUploadProgress();
      useStore.getState().setUploadProgress(null);
      return;
    }

    hideLoadingIndicator();
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);

    const assistantMessage: Message = {
      id: response.id,
      role: 'assistant',
      content: response.content,
      sources: response.sources,
      generated_images: response.generated_images,
      files: response.files,
      created_at: response.created_at,
    };

    const messagesContainer = getElementById<HTMLDivElement>('messages');
    if (messagesContainer) {
      const hasImagesToLoad = assistantMessage.files?.some(
        (f) => f.type.startsWith('image/') && !f.previewUrl
      );
      const wasAtBottom = isScrolledToBottom(messagesContainer);
      if (hasImagesToLoad && wasAtBottom) {
        enableScrollOnImageLoad();
      }
      addMessageToUI(assistantMessage, messagesContainer);
      if (hasImagesToLoad && wasAtBottom) {
        // Scroll to bottom immediately to ensure images are visible
        // IntersectionObserver will re-check after scroll and fire for visible images
        programmaticScrollToBottom(messagesContainer, false);
        // Use double RAF to ensure scroll completed and layout settled
        // Then check if images need manual triggering (fallback)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const messageEl = messagesContainer.querySelector(
              `[data-message-id="${assistantMessage.id}"]`
            );
            if (messageEl) {
              const images = messageEl.querySelectorAll<HTMLImageElement>(
                'img[data-message-id][data-file-index]:not([src])'
              );
              // If images are visible but haven't started loading, manually trigger
              // This is a fallback in case IntersectionObserver didn't fire
              images.forEach((img) => {
                const rect = img.getBoundingClientRect();
                const containerRect = messagesContainer.getBoundingClientRect();
                const isVisible = rect.top < containerRect.bottom && rect.bottom > containerRect.top;
                if (isVisible && !img.src) {
                  // Image is visible but not loading - unobserve and re-observe to trigger check
                  getThumbnailObserver().unobserve(img);
                  observeThumbnail(img);
                }
              });
            }
            checkScrollButtonVisibility();
          });
        });
      } else {
        if (wasAtBottom) {
          programmaticScrollToBottom(messagesContainer);
        }
        requestAnimationFrame(() => {
          checkScrollButtonVisibility();
        });
      }
    }

    // Update conversation title if this was the first message (title comes from response)
    updateConversationTitle(convId, response.title);

    // Update conversation cost
    await updateConversationCost(convId);

    // Update sync manager's local message count (user message + assistant response = 2)
    // This is done here (after success) to ensure the count is updated before any sync
    getSyncManager()?.incrementLocalMessageCount(convId, 2);
  } catch (error) {
    hideLoadingIndicator();
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);

    // Check if conversation is still current before showing errors
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    if (!isCurrentConversation) {
      // User switched conversations - silently handle error, message will be in DB
      return;
    }

    throw error;
  } finally {
    // Clean up request tracking
    activeRequests.delete(requestId);
    // Remove active request from store
    useStore.getState().removeActiveRequest(convId);
    // Ensure upload progress is hidden (safety net)
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);
  }
}
