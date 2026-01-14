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
import type { Message, ThinkingState, ToolMetadata, ThinkingTraceItem } from '../types/api';
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
  let messageEl = addStreamingMessage(convId);
  let fullContent = '';
  // Track thinking state locally for store sync (independent of Messages.ts context)
  const localThinkingState: ThinkingState = {
    isThinking: true,
    thinkingText: '',
    activeTool: null,
    activeToolDetail: undefined,
    completedTools: [],
    trace: [],
  };
  const requestId = `stream-${convId}-${Date.now()}`;
  const abortController = new AbortController();
  // Track if message was successfully sent (for incrementing count in finally block)
  let messageSuccessful = false;

  // Track this request with abort controller
  const request: ActiveRequest = {
    conversationId: convId,
    type: 'stream',
    abortController,
  };
  activeRequests.set(requestId, request);

  // Note: The message element is tracked in Messages.ts via currentStreamingContext
  // (set by addStreamingMessage). Use getStreamingMessageElement(convId) to retrieve it.

  // Register active request in store for UI restoration on conversation switch
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'stream',
    content: '',
    thinkingState: undefined,
  });

  // Mark conversation as streaming to prevent sync race conditions
  getSyncManager()?.setConversationStreaming(convId, true);

  // Set streaming state in store for UI updates (stop button)
  useStore.getState().setStreamingConversation(convId);

  // Show upload progress for requests with files (indeterminate since fetch doesn't support progress)
  const hasFiles = files && files.length > 0;
  if (hasFiles) {
    showUploadProgress();
    // Show indeterminate progress (no percentage available with fetch)
    updateUploadProgress(0);
    const progressText = document.querySelector('.upload-progress-text');
    if (progressText) {
      progressText.textContent = 'Uploading...';
    }
  }

  try {
    // Hide upload progress once streaming starts (upload complete)
    let uploadProgressHidden = false;

    // Check if conversation is still current before processing each event
    for await (const event of chat.stream(convId, message, files, forceTools, abortController, anonymousMode)) {
      // Hide upload progress on first event (means upload is complete)
      if (hasFiles && !uploadProgressHidden) {
        hideUploadProgress();
        useStore.getState().setUploadProgress(null);
        uploadProgressHidden = true;
      }
      // Check if user switched conversations - if so, update store but don't update UI
      const store = useStore.getState();
      const isCurrentConversation = store.currentConversation?.id === convId;

      // Get the current message element from Messages.ts (may have been restored after conversation switch)
      // This is the single source of truth for the streaming element
      const currentMessageEl = getStreamingMessageElement(convId);
      if (currentMessageEl) {
        messageEl = currentMessageEl;
      }

      if (event.type === 'user_message_saved') {
        // Update user message ID from temp to real ID immediately (before streaming completes)
        // This enables lightbox to fetch files during streaming
        if (event.user_message_id) {
          updateUserMessageId(tempUserMessageId, event.user_message_id);
        }
      } else if (event.type === 'thinking') {
        // Update local thinking state (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'thinking', event.text);
        // Update UI only if this is the current conversation
        if (isCurrentConversation) {
          updateStreamingThinking(event.text);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'tool_start') {
        // Update local thinking state (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'tool_start', event.tool, event.detail, event.metadata);
        // Tool execution started (with optional detail like search query, URL, or prompt)
        if (isCurrentConversation) {
          updateStreamingToolStart(event.tool, event.detail, event.metadata);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'tool_detail') {
        // Update local thinking state with the new detail (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'tool_detail', event.tool, event.detail);
        // Update the tool detail in the UI (only if current conversation)
        if (isCurrentConversation) {
          updateStreamingToolDetail(event.tool, event.detail);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'tool_end') {
        // Update local thinking state (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'tool_end', event.tool);
        // Tool execution completed
        if (isCurrentConversation) {
          updateStreamingToolEnd(event.tool);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'token') {
        fullContent += event.text;
        // Mark thinking as no longer active when content starts flowing
        if (localThinkingState.isThinking) {
          localThinkingState.isThinking = false;
        }
        // Always update the store content for restoration
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
        // Update UI only if this is the current conversation
        if (isCurrentConversation) {
          updateStreamingMessage(messageEl, fullContent);
        }
      } else if (event.type === 'done') {
        log.info('Streaming complete', { conversationId: convId, messageId: event.id });

        // Update user message ID from temp to real ID (for file fetching in lightbox)
        if (event.user_message_id) {
          updateUserMessageId(tempUserMessageId, event.user_message_id);
        }

        // Only update UI if this is still the current conversation
        if (isCurrentConversation) {
          finalizeStreamingMessage(messageEl, event.id, event.created_at, event.sources, event.generated_images, event.files, 'assistant', event.language);

          // Handle scroll-to-bottom for lazy-loaded images (same logic as batch mode)
          const messagesContainer = getElementById<HTMLDivElement>('messages');
          if (messagesContainer && event.files) {
            const hasImagesToLoad = event.files.some(
              (f) => f.type.startsWith('image/') && !f.previewUrl
            );
            const wasAtBottom = isScrolledToBottom(messagesContainer);
            if (hasImagesToLoad && wasAtBottom) {
              enableScrollOnImageLoad();
              programmaticScrollToBottom(messagesContainer, false);
              requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                  const images = messageEl.querySelectorAll<HTMLImageElement>(
                    'img[data-message-id][data-file-index]:not([src])'
                  );
                  images.forEach((img) => {
                    const rect = img.getBoundingClientRect();
                    const containerRect = messagesContainer.getBoundingClientRect();
                    const isVisible = rect.top < containerRect.bottom && rect.bottom > containerRect.top;
                    if (isVisible && !img.src) {
                      getThumbnailObserver().unobserve(img);
                      observeThumbnail(img);
                    }
                  });
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
          updateConversationTitle(convId, event.title);

          // Update conversation cost
          await updateConversationCost(convId);

          // Mark as successful for message count increment in finally block
          messageSuccessful = true;
        }
      } else if (event.type === 'error') {
        log.error('Stream error', { message: event.message, conversationId: convId });
        // Keep partial content if any was received
        if (fullContent.trim()) {
          // Mark message as incomplete but keep the content
          messageEl.classList.add('message-incomplete');
        } else {
          messageEl.remove();
        }
        // Convert error event to ApiError and throw - outer sendMessage catch handles draft/toast
        const errorEvent = event as { message?: string; code?: string; retryable?: boolean };
        const streamError = new ApiError(
          errorEvent.message || 'Failed to generate response.',
          errorEvent.code === 'TIMEOUT' ? 408 : 500,
          {
            code: errorEvent.code,
            retryable: errorEvent.retryable ?? false,
            isTimeout: errorEvent.code === 'TIMEOUT',
          }
        );
        throw streamError;
      }
    }
  } catch (error) {
    // Check if this was a user-initiated abort
    if (error instanceof Error && error.name === 'AbortError') {
      log.info('Stream aborted by user', { conversationId: convId });
      // User actively stopped - remove the streaming assistant message from UI
      messageEl.remove();
      // Show a toast so user knows the action was successful
      toast.info('Response stopped.');
      // Note: Partial messages may remain in the backend database.
      // A future message delete button can be used to clean them up if needed.
      // Don't re-throw - this is intentional user action, not an error
      return;
    }

    log.error('Streaming failed', { error, conversationId: convId });

    // Check if conversation is still current before cleaning up UI
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    // Keep partial content if any was received, otherwise remove the message element
    if (fullContent.trim()) {
      messageEl.classList.add('message-incomplete');
    } else {
      messageEl.remove();
    }

    // Re-throw error if this is still the current conversation
    // Outer sendMessage catch handles draft saving and toast display
    if (isCurrentConversation) {
      throw error;
    }
    // If user switched conversations, silently swallow the error
  } finally {
    // Clean up request tracking and streaming context
    activeRequests.delete(requestId);
    // Note: cleanupStreamingContext() handles clearing the element reference in Messages.ts
    cleanupStreamingContext();

    // Remove active request from store
    useStore.getState().removeActiveRequest(convId);

    // Ensure upload progress is hidden (safety net)
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);

    // IMPORTANT: Increment local message count BEFORE clearing streaming flag
    // This prevents a race condition where sync happens between clearing the flag
    // and incrementing the count, causing false "new messages available" banner
    if (messageSuccessful) {
      getSyncManager()?.incrementLocalMessageCount(convId, 2);
    }

    // Clear streaming flag so sync can update this conversation again
    getSyncManager()?.setConversationStreaming(convId, false);

    // Clear streaming state in store (for stop button UI)
    useStore.getState().setStreamingConversation(null);
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
