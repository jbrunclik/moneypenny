import { escapeHtml, getElementById, scrollToBottom, isScrolledToBottom, clearElement } from '../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../utils/markdown';
import {
  observeThumbnail,
  markProgrammaticScrollStart,
  markProgrammaticScrollEnd,
  countVisibleImagesForScroll,
  setDeferImageObservation,
} from '../utils/thumbnails';
import { createUserAvatarElement } from '../utils/avatar';
import { checkScrollButtonVisibility } from './ScrollToBottom';
import {
  AI_AVATAR_SVG,
  getFileIcon,
  DOWNLOAD_ICON,
  COPY_ICON,
  SOURCES_ICON,
  SPARKLES_ICON,
  COST_ICON,
} from '../utils/icons';
import { costs } from '../api/client';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import {
  createThinkingIndicator,
  updateThinkingIndicator,
  finalizeThinkingIndicator,
  createThinkingState,
  addThinkingToTrace,
  addToolStartToTrace,
  markToolCompletedInTrace,
} from './ThinkingIndicator';
import type { Message, FileMetadata, Source, GeneratedImage, ThinkingState } from '../types/api';

const log = createLogger('messages');

/**
 * Format a timestamp for display using system locale
 * Shows time for today, "Yesterday HH:MM" for yesterday, or locale date + time for older
 */
function formatMessageTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  const messageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  const timeStr = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

  if (messageDay.getTime() === today.getTime()) {
    return timeStr;
  } else if (messageDay.getTime() === yesterday.getTime()) {
    // Use Intl.RelativeTimeFormat for localized "yesterday"
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    const yesterdayStr = rtf.formatToParts(-1, 'day').find(p => p.type === 'literal')?.value || 'Yesterday';
    return `${yesterdayStr} ${timeStr}`;
  } else {
    // Full locale-aware date formatting
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
}

/**
 * Render all messages in the container
 */
export function renderMessages(messages: Message[]): void {
  log.debug('Rendering messages', { count: messages.length });
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  if (messages.length === 0) {
    container.innerHTML = `
      <div class="welcome-message">
        <h2>Welcome to AI Chatbot</h2>
        <p>Start a conversation with Gemini AI</p>
      </div>
    `;
    return;
  }

  clearElement(container);

  // Defer image observation until after we count them
  // This prevents IntersectionObserver from firing synchronously before we count
  setDeferImageObservation(true);

  messages.forEach((msg) => {
    addMessageToUI(msg, container);
  });

  // Always scroll to bottom first - this ensures:
  // 1. User sees the latest messages immediately
  // 2. Images at the bottom become visible
  // Mark as programmatic so the user scroll listener doesn't disable auto-scroll
  // Wait for layout to settle before scrolling (scrollHeight needs to be accurate)
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      markProgrammaticScrollStart();
      scrollToBottom(container);
      // Wait for scroll to complete before clearing the programmatic flag
      requestAnimationFrame(() => {
        markProgrammaticScrollEnd();
      });
    });
  });

  // Count visible images after scroll completes and layout has settled
  // Use double requestAnimationFrame to ensure layout is fully settled
  // Then observe in setTimeout(0) to ensure counting happens in current tick, observation in next tick
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      // Count images now that they're visible after scroll and layout has settled
      countVisibleImagesForScroll();

      // Use setTimeout(0) to observe in the next event loop tick
      // This ensures counting happens in the current tick, observation in the next tick
      // This prevents IntersectionObserver from firing synchronously before we count
      setTimeout(() => {
        // Now observe all images that need loading
        // This will trigger IntersectionObserver, but we've already counted visible ones
        // The scrollTracked flag prevents double-counting in IntersectionObserver callback
        setDeferImageObservation(false);
        const imagesToObserve = container.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]:not([src])'
        );
        imagesToObserve.forEach((img) => {
          observeThumbnail(img);
        });
      }, 0);
    });
  });

  // Final check after a short delay to catch any edge cases
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      countVisibleImagesForScroll();
      checkScrollButtonVisibility();
    });
  });
}

/**
 * Add a single message to the UI
 */
export function addMessageToUI(
  message: Message,
  container: HTMLElement = getElementById('messages')!
): void {
  const messageEl = document.createElement('div');
  messageEl.className = `message ${message.role}`;
  messageEl.dataset.messageId = message.id;

  // Avatar
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  if (message.role === 'assistant') {
    avatar.innerHTML = AI_AVATAR_SVG;
  } else {
    // User avatar - show picture or initials
    const user = useStore.getState().user;
    const name = user?.name || user?.email || 'User';
    const avatarContent = createUserAvatarElement(user?.picture || undefined, name, '');
    // For message avatars, we add content to the existing div instead of replacing it
    if (avatarContent instanceof HTMLImageElement) {
      avatar.appendChild(avatarContent);
    } else {
      avatar.textContent = avatarContent.textContent;
    }
  }
  messageEl.appendChild(avatar);

  // Content wrapper
  const contentWrapper = document.createElement('div');
  contentWrapper.className = 'message-content-wrapper';

  // Render text content
  const content = document.createElement('div');
  content.className = 'message-content';

  if (message.role === 'assistant') {
    // Assistant: text first, then files inside the bubble (same as user)
    content.innerHTML = renderMarkdown(message.content);
    highlightAllCodeBlocks(content);
    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      content.appendChild(filesContainer);
    }
    contentWrapper.appendChild(content);
  } else {
    // User: text first, then files inside the bubble
    if (message.content) {
      content.innerHTML = `<p>${escapeHtml(message.content).replace(/\n/g, '<br>')}</p>`;
    }
    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      content.appendChild(filesContainer);
    }
    contentWrapper.appendChild(content);
  }

  // Add message actions (timestamp + sources/imagegen/cost buttons + copy button)
  const actions = document.createElement('div');
  actions.className = 'message-actions';
  const timeStr = message.created_at ? formatMessageTime(message.created_at) : '';
  const hasSources = message.sources && message.sources.length > 0;
  const hasGeneratedImages = message.generated_images && message.generated_images.length > 0;
  // Only show cost button for assistant messages (they have costs)
  const showCostButton = message.role === 'assistant';
  actions.innerHTML = `
    ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
    ${hasSources ? `<button class="message-sources-btn" title="View sources (${message.sources!.length})">${SOURCES_ICON}</button>` : ''}
    ${hasGeneratedImages ? `<button class="message-imagegen-btn" title="View image generation info">${SPARKLES_ICON}</button>` : ''}
    ${showCostButton ? `<button class="message-cost-btn" title="View message cost">${COST_ICON}</button>` : ''}
    <button class="message-copy-btn" title="Copy message">
      ${COPY_ICON}
    </button>
  `;

  // Add sources button click handler
  if (hasSources) {
    const sourcesBtn = actions.querySelector('.message-sources-btn');
    sourcesBtn?.addEventListener('click', () => {
      window.dispatchEvent(
        new CustomEvent('sources:open', {
          detail: message.sources,
        })
      );
    });
  }

  // Add generated images button click handler
  if (hasGeneratedImages) {
    const imagegenBtn = actions.querySelector('.message-imagegen-btn');
    imagegenBtn?.addEventListener('click', () => {
      // Add message_id to generated images for cost lookup
      const imagesWithMessageId = message.generated_images!.map(img => ({
        ...img,
        message_id: message.id,
      }));
      window.dispatchEvent(
        new CustomEvent('imagegen:open', {
          detail: imagesWithMessageId,
        })
      );
    });
  }

  // Add cost button click handler
  if (showCostButton) {
    const costBtn = actions.querySelector('.message-cost-btn');
    costBtn?.addEventListener('click', async () => {
      try {
        const costData = await costs.getMessageCost(message.id);
        window.dispatchEvent(
          new CustomEvent('message-cost:open', {
            detail: costData,
          })
        );
      } catch (error) {
        log.warn('Failed to fetch message cost', { error, messageId: message.id });
        // Silently fail - cost display is optional
      }
    });
  }

  contentWrapper.appendChild(actions);

  messageEl.appendChild(contentWrapper);
  container.appendChild(messageEl);
}

/**
 * Render files attached to a message
 */
function renderMessageFiles(files: FileMetadata[], messageId: string): HTMLElement {
  const container = document.createElement('div');
  container.className = 'message-files';

  // Separate images from other files
  const images = files.filter((f) => f.type.startsWith('image/'));
  const documents = files.filter((f) => !f.type.startsWith('image/'));

  // Render images in horizontal gallery
  if (images.length > 0) {
    const gallery = document.createElement('div');
    gallery.className = 'message-images';

    images.forEach((file) => {
      const fileIndex = files.indexOf(file);
      const imgWrapper = document.createElement('div');
      imgWrapper.className = 'message-image-wrapper';

      const img = document.createElement('img');
      img.className = 'message-image';
      img.alt = file.name;
      img.dataset.messageId = file.messageId || messageId;
      img.dataset.fileIndex = String(file.fileIndex ?? fileIndex);

      // If we have a local preview URL (just-uploaded file), use it directly
      // Otherwise, use lazy loading to fetch thumbnail from server
      if (file.previewUrl) {
        img.src = file.previewUrl;
      } else {
        // Add loading state for server-fetched images
        imgWrapper.classList.add('loading');

        // Add placeholder with filename
        const placeholder = document.createElement('span');
        placeholder.className = 'image-placeholder';
        placeholder.textContent = file.name;
        imgWrapper.appendChild(placeholder);

        img.loading = 'lazy';

        // Set up lazy loading - remove loading class from wrapper when loaded
        img.addEventListener('load', () => {
          imgWrapper.classList.remove('loading');
        });

        // Observe the image for lazy loading
        // Note: During renderMessages(), we'll also observe after counting to ensure
        // we count before IntersectionObserver fires, but we still need to observe here
        // for cases where images are added outside of renderMessages() (e.g., streaming)
        observeThumbnail(img);
      }

      // Click to open lightbox
      img.addEventListener('click', () => {
        window.dispatchEvent(
          new CustomEvent('lightbox:open', {
            detail: {
              messageId: img.dataset.messageId,
              fileIndex: img.dataset.fileIndex,
            },
          })
        );
      });

      imgWrapper.appendChild(img);
      gallery.appendChild(imgWrapper);
    });

    container.appendChild(gallery);
  }

  // Render documents as list
  if (documents.length > 0) {
    const list = document.createElement('div');
    list.className = 'message-documents';

    documents.forEach((file) => {
      const fileIndex = files.indexOf(file);
      const doc = document.createElement('div');
      doc.className = 'message-document';
      doc.innerHTML = `
        <span class="document-icon">${getFileIcon(file.type)}</span>
        <span class="document-name">${escapeHtml(file.name)}</span>
        <button class="document-download"
                data-message-id="${file.messageId || messageId}"
                data-file-index="${file.fileIndex ?? fileIndex}"
                title="Download">
          ${DOWNLOAD_ICON}
        </button>
      `;
      list.appendChild(doc);
    });

    container.appendChild(list);
  }

  return container;
}

/**
 * Streaming message context - holds state for the current streaming message
 */
interface StreamingMessageContext {
  element: HTMLElement;
  thinkingIndicator: HTMLElement;
  thinkingState: ThinkingState;
  /** Whether to auto-scroll during streaming - dynamically updated based on user scroll */
  shouldAutoScroll: boolean;
  /** Scroll listener cleanup function */
  scrollListenerCleanup: (() => void) | null;
}

// Global context for the current streaming message
let currentStreamingContext: StreamingMessageContext | null = null;

// Constants for streaming scroll behavior
const STREAMING_SCROLL_THRESHOLD_PX = 100; // Distance from bottom to consider "at bottom"
const STREAMING_SCROLL_CHECK_DEBOUNCE_MS = 50; // Debounce for scroll detection

/**
 * Add a streaming message placeholder
 * @returns Object with element and methods to update thinking state
 */
export function addStreamingMessage(): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';

  // Create thinking indicator
  const thinkingIndicator = createThinkingIndicator();
  const thinkingState = createThinkingState();

  messageEl.innerHTML = `
    <div class="message-avatar">${AI_AVATAR_SVG}</div>
    <div class="message-content-wrapper">
      <div class="message-content">
        <span class="streaming-cursor"></span>
      </div>
    </div>
  `;

  // Insert thinking indicator at the start of message-content
  const contentEl = messageEl.querySelector('.message-content');
  if (contentEl) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
  }

  // Check if user is at bottom BEFORE adding the message
  const wasAtBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

  // Store context for updates
  currentStreamingContext = {
    element: messageEl,
    thinkingIndicator,
    thinkingState,
    shouldAutoScroll: wasAtBottom,
    scrollListenerCleanup: null,
  };

  container.appendChild(messageEl);
  scrollToBottom(container);

  // Set up scroll listener to detect user scroll during streaming
  // This allows interrupting auto-scroll when scrolling up and resuming when scrolling back to bottom
  setupStreamingScrollListener(container);

  // Update button visibility after adding message and scrolling
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });

  return messageEl;
}

/**
 * Set up a scroll listener for streaming that:
 * 1. Disables auto-scroll when user scrolls up (away from bottom)
 * 2. Re-enables auto-scroll when user scrolls back to bottom
 */
function setupStreamingScrollListener(container: HTMLElement): void {
  if (!currentStreamingContext) return;

  // Clean up any existing listener
  if (currentStreamingContext.scrollListenerCleanup) {
    currentStreamingContext.scrollListenerCleanup();
  }

  let debounceTimeout: number | undefined;

  const scrollHandler = (): void => {
    if (!currentStreamingContext) return;

    // Debounce the scroll check to avoid excessive processing
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = window.setTimeout(() => {
      if (!currentStreamingContext) return;

      const atBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

      if (atBottom && !currentStreamingContext.shouldAutoScroll) {
        // User scrolled back to bottom - resume auto-scroll
        currentStreamingContext.shouldAutoScroll = true;
        log.debug('Streaming auto-scroll resumed (user scrolled to bottom)');
      } else if (!atBottom && currentStreamingContext.shouldAutoScroll) {
        // User scrolled away from bottom - disable auto-scroll
        currentStreamingContext.shouldAutoScroll = false;
        log.debug('Streaming auto-scroll paused (user scrolled up)');
      }
    }, STREAMING_SCROLL_CHECK_DEBOUNCE_MS);
  };

  container.addEventListener('scroll', scrollHandler, { passive: true });

  // Store cleanup function
  currentStreamingContext.scrollListenerCleanup = () => {
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
    container.removeEventListener('scroll', scrollHandler);
  };
}

/**
 * Clean up streaming context and scroll listener.
 * Called when streaming ends (success or error).
 */
export function cleanupStreamingContext(): void {
  if (currentStreamingContext) {
    if (currentStreamingContext.scrollListenerCleanup) {
      currentStreamingContext.scrollListenerCleanup();
    }
    currentStreamingContext = null;
  }
}

/**
 * Auto-scroll to keep the thinking indicator visible during streaming.
 * Only scrolls if auto-scroll is enabled (user hasn't scrolled away).
 */
function autoScrollForStreaming(): void {
  if (!currentStreamingContext?.shouldAutoScroll) return;

  const messagesContainer = getElementById('messages');
  if (messagesContainer) {
    scrollToBottom(messagesContainer);
  }
}

/**
 * Update the thinking state of the current streaming message
 */
export function updateStreamingThinking(thinkingText?: string): void {
  if (!currentStreamingContext) return;

  if (thinkingText) {
    addThinkingToTrace(currentStreamingContext.thinkingState, thinkingText);
  }
  currentStreamingContext.thinkingState.isThinking = true;

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll to keep thinking indicator visible
  autoScrollForStreaming();
}

/**
 * Signal that a tool has started executing
 * @param toolName The name of the tool
 * @param detail Optional detail (search query, URL, prompt)
 */
export function updateStreamingToolStart(toolName: string, detail?: string): void {
  if (!currentStreamingContext) return;

  addToolStartToTrace(currentStreamingContext.thinkingState, toolName, detail);

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll to keep tool indicator visible
  autoScrollForStreaming();
}

/**
 * Signal that a tool has finished executing
 */
export function updateStreamingToolEnd(toolName: string): void {
  if (!currentStreamingContext) return;

  markToolCompletedInTrace(currentStreamingContext.thinkingState, toolName);

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll after tool completion
  autoScrollForStreaming();
}

/**
 * Update streaming message content
 */
export function updateStreamingMessage(
  messageEl: HTMLElement,
  content: string
): void {
  const contentEl = messageEl.querySelector('.message-content');
  if (!contentEl) return;

  // Preserve thinking indicator if it exists
  const thinkingIndicator = contentEl.querySelector('.thinking-indicator');

  // Render markdown for the accumulated content
  contentEl.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';

  // Re-insert thinking indicator at the top
  if (thinkingIndicator) {
    contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
  }

  // When content starts flowing, mark thinking as done
  if (content && currentStreamingContext) {
    currentStreamingContext.thinkingState.isThinking = false;
    updateThinkingIndicator(
      currentStreamingContext.thinkingIndicator,
      currentStreamingContext.thinkingState
    );
  }

  // Auto-scroll if user was at bottom when streaming started
  autoScrollForStreaming();
}

/**
 * Finalize streaming message
 */
export function finalizeStreamingMessage(
  messageEl: HTMLElement,
  messageId: string,
  createdAt?: string,
  sources?: Source[],
  generatedImages?: GeneratedImage[],
  files?: FileMetadata[],
  role: 'user' | 'assistant' = 'assistant'
): void {
  messageEl.classList.remove('streaming');
  messageEl.dataset.messageId = messageId;

  // Remove cursor
  const cursor = messageEl.querySelector('.streaming-cursor');
  cursor?.remove();

  // Finalize thinking indicator and clean up streaming context
  if (currentStreamingContext && currentStreamingContext.element === messageEl) {
    finalizeThinkingIndicator(
      currentStreamingContext.thinkingIndicator,
      currentStreamingContext.thinkingState
    );
    // Clean up scroll listener
    if (currentStreamingContext.scrollListenerCleanup) {
      currentStreamingContext.scrollListenerCleanup();
    }
    // Clear the context
    currentStreamingContext = null;
  }

  // Apply syntax highlighting to code blocks
  const content = messageEl.querySelector('.message-content');
  if (content) {
    highlightAllCodeBlocks(content as HTMLElement);

    // Add files (generated images) inside the content bubble
    if (files && files.length > 0) {
      const filesContainer = renderMessageFiles(files, messageId);
      content.appendChild(filesContainer);
    }
  }

  // Add message actions (timestamp + sources/imagegen buttons + copy button)
  const contentWrapper = messageEl.querySelector('.message-content-wrapper');
  if (contentWrapper && !contentWrapper.querySelector('.message-actions')) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const timeStr = createdAt ? formatMessageTime(createdAt) : '';
    const hasSources = sources && sources.length > 0;
    const hasGeneratedImages = generatedImages && generatedImages.length > 0;
    // Only show cost button for assistant messages (they have costs)
    const showCostButton = role === 'assistant';
    actions.innerHTML = `
      ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
      ${hasSources ? `<button class="message-sources-btn" title="View sources (${sources!.length})">${SOURCES_ICON}</button>` : ''}
      ${hasGeneratedImages ? `<button class="message-imagegen-btn" title="View image generation info">${SPARKLES_ICON}</button>` : ''}
      ${showCostButton ? `<button class="message-cost-btn" title="View message cost">${COST_ICON}</button>` : ''}
      <button class="message-copy-btn" title="Copy message">
        ${COPY_ICON}
      </button>
    `;

    // Add sources button click handler
    if (hasSources) {
      const sourcesBtn = actions.querySelector('.message-sources-btn');
      sourcesBtn?.addEventListener('click', () => {
        window.dispatchEvent(
          new CustomEvent('sources:open', {
            detail: sources,
          })
        );
      });
    }

    // Add generated images button click handler
    if (hasGeneratedImages) {
      const imagegenBtn = actions.querySelector('.message-imagegen-btn');
      imagegenBtn?.addEventListener('click', () => {
        // Add message_id to generated images for cost lookup
        const imagesWithMessageId = generatedImages!.map(img => ({
          ...img,
          message_id: messageId,
        }));
        window.dispatchEvent(
          new CustomEvent('imagegen:open', {
            detail: imagesWithMessageId,
          })
        );
      });
    }

    // Add cost button click handler
    if (showCostButton) {
      const costBtn = actions.querySelector('.message-cost-btn');
      costBtn?.addEventListener('click', async () => {
        try {
          const costData = await costs.getMessageCost(messageId);
          window.dispatchEvent(
            new CustomEvent('message-cost:open', {
              detail: costData,
            })
          );
        } catch (error) {
          log.warn('Failed to fetch message cost', { error, messageId });
          // Silently fail - cost display is optional
        }
      });
    }

    contentWrapper.appendChild(actions);
  }

  // Update button visibility after finalizing message
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });
}

/**
 * Show loading indicator in messages
 */
export function showLoadingIndicator(): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Remove existing loading indicator
  hideLoadingIndicator();

  const loading = document.createElement('div');
  loading.className = 'message-loading';
  loading.innerHTML = `
    <div class="message-avatar">${AI_AVATAR_SVG}</div>
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;
  container.appendChild(loading);
  scrollToBottom(container);
}

/**
 * Hide loading indicator
 */
export function hideLoadingIndicator(): void {
  const loading = document.querySelector('.message-loading');
  loading?.remove();
}

/**
 * Show conversation loading overlay
 */
export function showConversationLoader(): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Remove existing loader
  hideConversationLoader();

  const loader = document.createElement('div');
  loader.className = 'conversation-loader';
  loader.innerHTML = `
    <div class="conversation-loader-content">
      <div class="loading-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <p>Loading conversation...</p>
    </div>
  `;
  container.appendChild(loader);
}

/**
 * Hide conversation loading overlay
 */
export function hideConversationLoader(): void {
  const loader = document.querySelector('.conversation-loader');
  loader?.remove();
}

/**
 * Update chat title in mobile header
 */
export function updateChatTitle(title: string): void {
  const titleEl = getElementById<HTMLSpanElement>('current-chat-title');
  if (titleEl) {
    titleEl.textContent = title;
  }
}