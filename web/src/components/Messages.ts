import { escapeHtml, getElementById, scrollToBottom, isScrolledToBottom, clearElement } from '../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../utils/markdown';
import { linkifyText } from '../utils/linkify';
import {
  observeThumbnail,
  markProgrammaticScrollStart,
  markProgrammaticScrollEnd,
  countVisibleImagesForScroll,
  setDeferImageObservation,
  programmaticScrollToBottom,
} from '../utils/thumbnails';
import { createUserAvatarElement } from '../utils/avatar';
import { checkScrollButtonVisibility, setStreamingPausedIndicator } from './ScrollToBottom';
import {
  AI_AVATAR,
  getFileIcon,
  DOWNLOAD_ICON,
  COPY_ICON,
  SOURCES_ICON,
  SPARKLES_ICON,
  COST_ICON,
  DELETE_ICON,
  SPEAKER_ICON,
} from '../utils/icons';
import { costs, conversations } from '../api/client';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import {
  LOAD_OLDER_MESSAGES_THRESHOLD_PX,
  LOAD_NEWER_MESSAGES_THRESHOLD_PX,
  INFINITE_SCROLL_DEBOUNCE_MS,
  STREAMING_SCROLL_THRESHOLD_PX,
  STREAMING_SCROLL_RESUME_DEBOUNCE_MS,
} from '../config';
import { PaginationDirection } from '../types/api';
import {
  createThinkingIndicator,
  updateThinkingIndicator,
  finalizeThinkingIndicator,
  createThinkingState,
  addThinkingToTrace,
  addToolStartToTrace,
  updateToolDetailInTrace,
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
/**
 * Options for rendering messages
 */
interface RenderMessagesOptions {
  /**
   * If true, skip the automatic scroll-to-bottom after rendering.
   * Useful when the caller wants to scroll to a specific message (e.g., search navigation).
   */
  skipScrollToBottom?: boolean;
}

export function renderMessages(messages: Message[], options: RenderMessagesOptions = {}): void {
  log.debug('Rendering messages', { count: messages.length, skipScrollToBottom: options.skipScrollToBottom });
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

  // Scroll to bottom by default, unless caller wants to scroll to a specific element
  // (e.g., search navigation scrolls to the target message instead)
  if (!options.skipScrollToBottom) {
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
  }

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

// Track scroll position for orientation change handling
let savedScrollPercentage: number | null = null;
let orientationChangeCleanup: (() => void) | null = null;

/**
 * Initialize orientation change handler to preserve scroll position.
 * When device orientation changes, layout reflows can cause scroll position loss.
 * This saves the scroll position as a percentage before orientation change and
 * restores it after layout settles.
 */
export function initOrientationChangeHandler(): void {
  // Clean up any existing handler
  if (orientationChangeCleanup) {
    orientationChangeCleanup();
  }

  const handleOrientationChange = (): void => {
    const container = getElementById<HTMLDivElement>('messages');
    if (!container) return;

    // Save scroll position as a percentage of total scrollable height
    const maxScrollTop = container.scrollHeight - container.clientHeight;
    if (maxScrollTop > 0) {
      savedScrollPercentage = container.scrollTop / maxScrollTop;
    } else {
      savedScrollPercentage = 1; // At bottom if no scrollable content
    }

    log.debug('Orientation change: saved scroll percentage', { savedScrollPercentage });

    // After orientation change, layout will reflow. Wait for it to settle and restore position.
    // Use multiple RAFs + timeout to ensure layout has fully settled
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setTimeout(() => {
          if (savedScrollPercentage !== null) {
            const newMaxScrollTop = container.scrollHeight - container.clientHeight;
            if (newMaxScrollTop > 0) {
              container.scrollTop = savedScrollPercentage * newMaxScrollTop;
              log.debug('Orientation change: restored scroll position', {
                savedScrollPercentage,
                newScrollTop: container.scrollTop,
              });
            }
            savedScrollPercentage = null;
          }
        }, 100); // Small delay to ensure layout has fully settled
      });
    });
  };

  window.addEventListener('orientationchange', handleOrientationChange);

  // Also handle resize as fallback (some devices don't fire orientationchange)
  let resizeTimeout: number | undefined;
  let lastWidth = window.innerWidth;
  let lastHeight = window.innerHeight;

  const handleResize = (): void => {
    // Only act on significant dimension changes that indicate orientation change
    // (width/height swap, not keyboard opening which only changes height)
    const currentWidth = window.innerWidth;
    const currentHeight = window.innerHeight;

    const widthChanged = Math.abs(currentWidth - lastWidth) > 100;
    const heightChanged = Math.abs(currentHeight - lastHeight) > 100;
    const dimensionsSwapped =
      (lastWidth > lastHeight && currentHeight > currentWidth) ||
      (lastHeight > lastWidth && currentWidth > currentHeight);

    if (dimensionsSwapped || (widthChanged && heightChanged)) {
      // Clear any pending timeout and handle immediately
      if (resizeTimeout) {
        clearTimeout(resizeTimeout);
      }
      resizeTimeout = window.setTimeout(() => {
        handleOrientationChange();
        lastWidth = currentWidth;
        lastHeight = currentHeight;
      }, 50);
    } else {
      // Just update the last dimensions for future comparison
      lastWidth = currentWidth;
      lastHeight = currentHeight;
    }
  };

  window.addEventListener('resize', handleResize);

  orientationChangeCleanup = () => {
    window.removeEventListener('orientationchange', handleOrientationChange);
    window.removeEventListener('resize', handleResize);
    if (resizeTimeout) {
      clearTimeout(resizeTimeout);
    }
  };
}

/**
 * Create message actions container with all buttons and handlers.
 * This centralizes the logic for creating message action buttons (sources, imagegen, cost, speak, delete, copy)
 * to avoid duplication between addMessageToUI() and finalizeStreamingMessage().
 */
function createMessageActions(
  messageId: string,
  createdAt: string | undefined,
  sources: Source[] | undefined,
  generatedImages: GeneratedImage[] | undefined,
  role: 'user' | 'assistant',
  language?: string
): HTMLElement {
  const actions = document.createElement('div');
  actions.className = 'message-actions';
  const timeStr = createdAt ? formatMessageTime(createdAt) : '';
  const hasSources = sources && sources.length > 0;
  const hasGeneratedImages = generatedImages && generatedImages.length > 0;
  // Only show cost button for assistant messages (they have costs)
  const showCostButton = role === 'assistant';
  // Only show speak button for assistant messages and when speechSynthesis is supported
  const showSpeakButton = role === 'assistant' && typeof speechSynthesis !== 'undefined';
  actions.innerHTML = `
    ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
    ${hasSources ? `<button class="message-sources-btn" title="View sources (${sources!.length})">${SOURCES_ICON}</button>` : ''}
    ${hasGeneratedImages ? `<button class="message-imagegen-btn" title="View image generation info">${SPARKLES_ICON}</button>` : ''}
    ${showCostButton ? `<button class="message-cost-btn" title="View message cost">${COST_ICON}</button>` : ''}
    ${showSpeakButton ? `<button class="message-speak-btn" title="Read aloud">${SPEAKER_ICON}</button>` : ''}
    <button class="message-delete-btn" title="Delete message">
      ${DELETE_ICON}
    </button>
    <button class="message-copy-btn" title="Copy message">
      ${COPY_ICON}
    </button>
  `;

  // Attach delete button handler
  // IMPORTANT: Reads messageId from data-message-id attribute, not from closure,
  // to ensure we use the real ID even after updateUserMessageId() updates it.
  const deleteBtn = actions.querySelector('.message-delete-btn');
  deleteBtn?.addEventListener('click', (e) => {
    // Get the current message ID from the DOM (may have been updated from temp to real ID)
    // Use getAttribute for reliability (works even if dataset isn't set)
    // IMPORTANT: closest() must find the .message element that contains this button
    // We use the event target to ensure we're getting the right element
    const button = e.currentTarget as HTMLElement;
    const messageEl = button.closest('.message') as HTMLElement;
    if (!messageEl) {
      log.error('Failed to find message element for deletion', { messageId, button });
      return;
    }
    // Read the attribute directly - this will have the updated ID if updateUserMessageId() was called
    // IMPORTANT: getAttribute reads the actual HTML attribute, which is updated by dataset.messageId =
    const attrValue = messageEl.getAttribute('data-message-id');
    const datasetValue = messageEl.dataset.messageId;
    const currentMessageId = attrValue || datasetValue;

    if (!currentMessageId) {
      log.error('Failed to get message ID from DOM attribute', {
        messageId,
        element: messageEl,
        hasAttribute: messageEl.hasAttribute('data-message-id'),
        attrValue,
        datasetValue,
      });
      return;
    }

    // CRITICAL: If we're still getting the temp ID, something is wrong
    // The DOM should have been updated by updateUserMessageId()
    if (currentMessageId.startsWith('temp-')) {
      log.error('Delete handler still seeing temp ID - DOM not updated?', {
        currentMessageId,
        closureId: messageId,
        attrValue,
        datasetValue,
      });
      // Don't return - try to delete anyway, but log the issue
    }

    // Always use the ID from the DOM - never use the fallback from closure
    // This ensures we use the real ID even after updateUserMessageId() updates it
    log.debug('Deleting message', { messageId: currentMessageId, fromDOM: true, closureId: messageId });
    window.dispatchEvent(
      new CustomEvent('message:delete', {
        detail: { messageId: currentMessageId },
      })
    );
  });

  // Attach sources button handler
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

  // Attach generated images button handler
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

  // Attach cost button handler
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

  // Attach speak button handler
  if (showSpeakButton) {
    const speakBtn = actions.querySelector('.message-speak-btn');
    speakBtn?.addEventListener('click', (e) => {
      const button = e.currentTarget as HTMLElement;
      const messageEl = button.closest('.message') as HTMLElement;
      if (!messageEl) {
        log.error('Failed to find message element for speak', { messageId });
        return;
      }

      const messageContent = messageEl.querySelector('.message-content');
      if (!messageContent) {
        log.error('Failed to find message content for speak', { messageId });
        return;
      }

      window.dispatchEvent(
        new CustomEvent('message:speak', {
          detail: {
            messageId,
            content: messageContent.textContent || '',
            language,
          },
        })
      );
    });
  }

  return actions;
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
    avatar.innerHTML = AI_AVATAR;
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
      // Escape HTML, replace newlines, then linkify URLs
      const escapedContent = escapeHtml(message.content).replace(/\n/g, '<br>');
      const linkedContent = linkifyText(escapedContent);
      content.innerHTML = `<p>${linkedContent}</p>`;
    }
    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      content.appendChild(filesContainer);
    }
    contentWrapper.appendChild(content);
  }

  // Create message actions with all buttons and handlers
  const actions = createMessageActions(
    message.id,
    message.created_at,
    message.sources,
    message.generated_images,
    message.role,
    message.language
  );

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

      // Mark images with temp IDs as pending (lightbox disabled until real ID received)
      const effectiveMessageId = file.messageId || messageId;
      if (effectiveMessageId.startsWith('temp-')) {
        img.dataset.pending = 'true';
      }

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

      // Click to open lightbox (only if not pending)
      img.addEventListener('click', () => {
        if (img.dataset.pending === 'true') {
          // Image still has temp ID - lightbox would fail
          return;
        }
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
      // Make filename clickable to open in new tab (for PDFs), download button for saving
      doc.innerHTML = `
        <span class="document-icon">${getFileIcon(file.type)}</span>
        <a class="document-name document-preview"
           href="#"
           data-message-id="${file.messageId || messageId}"
           data-file-index="${file.fileIndex ?? fileIndex}"
           data-file-name="${escapeHtml(file.name)}"
           data-file-type="${file.type}"
           title="Open in new tab">${escapeHtml(file.name)}</a>
        <button class="document-download"
                data-message-id="${file.messageId || messageId}"
                data-file-index="${file.fileIndex ?? fileIndex}"
                data-file-name="${escapeHtml(file.name)}"
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
  /** Conversation ID this streaming context belongs to */
  conversationId: string;
}

// Global context for the current streaming message
let currentStreamingContext: StreamingMessageContext | null = null;

// Track the previous scroll position to detect scroll direction
// Used to distinguish user scrolls (up) from our programmatic scrolls (always to bottom)
let previousScrollTop = 0;

/**
 * Add a streaming message placeholder
 * @param conversationId - The ID of the conversation this streaming message belongs to
 * @returns Object with element and methods to update thinking state
 */
export function addStreamingMessage(conversationId: string): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';

  // Create thinking indicator
  const thinkingIndicator = createThinkingIndicator();
  const thinkingState = createThinkingState();

  messageEl.innerHTML = `
    <div class="message-avatar">${AI_AVATAR}</div>
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
    conversationId,
  };

  container.appendChild(messageEl);
  programmaticScrollToBottom(container);

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
 * 1. IMMEDIATELY disables auto-scroll when user scrolls up (away from bottom)
 * 2. Re-enables auto-scroll (with debounce) when user scrolls back to bottom
 *
 * CRITICAL: We must distinguish between user scrolls and our programmatic scrolls.
 * Our scrollToBottom() always scrolls DOWN (increases scrollTop), so if scrollTop
 * DECREASES, it must be a user scroll. This direction-based detection is more
 * reliable than time-based detection because it works regardless of event timing.
 */
function setupStreamingScrollListener(container: HTMLElement): void {
  if (!currentStreamingContext) return;

  // Clean up any existing listener
  if (currentStreamingContext.scrollListenerCleanup) {
    currentStreamingContext.scrollListenerCleanup();
  }

  // Initialize previous scroll position
  previousScrollTop = container.scrollTop;

  // Debounce timeout is ONLY used for re-enabling auto-scroll (when user scrolls back to bottom)
  // This prevents rapid re-enabling when user is scrolling around near the bottom
  let resumeDebounceTimeout: number | undefined;

  const scrollHandler = (): void => {
    if (!currentStreamingContext) return;

    const currentScrollTop = container.scrollTop;

    // iOS Safari momentum scroll can cause scrollTop to temporarily go negative
    // (rubber-banding at top) or past the max (rubber-banding at bottom).
    // Ignore these out-of-bounds values to prevent false user-scroll detection.
    const maxScrollTop = container.scrollHeight - container.clientHeight;
    if (currentScrollTop < 0 || currentScrollTop > maxScrollTop) {
      return; // Ignore rubber-banding scroll events
    }

    const scrolledUp = currentScrollTop < previousScrollTop;
    previousScrollTop = currentScrollTop;

    // If user scrolled UP, they want to read earlier content - disable auto-scroll immediately
    // Our programmatic scrollToBottom() never scrolls up, so this is definitely a user action
    if (scrolledUp && currentStreamingContext.shouldAutoScroll) {
      currentStreamingContext.shouldAutoScroll = false;
      log.debug('Streaming auto-scroll paused (user scrolled up)');

      // Show visual indicator on scroll button
      setStreamingPausedIndicator(true);

      // Clear any pending resume timeout
      if (resumeDebounceTimeout) {
        clearTimeout(resumeDebounceTimeout);
        resumeDebounceTimeout = undefined;
      }
      return;
    }

    // Check if at bottom for re-enabling auto-scroll
    const atBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

    if (atBottom && !currentStreamingContext.shouldAutoScroll) {
      // User scrolled back to bottom - use debounce to re-enable auto-scroll
      // This prevents rapid toggling when user is scrolling around near the bottom
      if (resumeDebounceTimeout) {
        clearTimeout(resumeDebounceTimeout);
      }

      resumeDebounceTimeout = window.setTimeout(() => {
        if (!currentStreamingContext) return;

        // Re-check position after debounce (user might have scrolled away again)
        const stillAtBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);
        if (stillAtBottom && !currentStreamingContext.shouldAutoScroll) {
          currentStreamingContext.shouldAutoScroll = true;
          log.debug('Streaming auto-scroll resumed (user scrolled to bottom)');

          // Clear the visual indicator
          setStreamingPausedIndicator(false);
        }
        resumeDebounceTimeout = undefined;
      }, STREAMING_SCROLL_RESUME_DEBOUNCE_MS);
    }
  };

  container.addEventListener('scroll', scrollHandler, { passive: true });

  // Store cleanup function
  currentStreamingContext.scrollListenerCleanup = () => {
    if (resumeDebounceTimeout) {
      clearTimeout(resumeDebounceTimeout);
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
  // Always clear the streaming paused indicator when streaming ends
  setStreamingPausedIndicator(false);
}

/**
 * Check if there is an active streaming context
 */
export function hasActiveStreamingContext(): boolean {
  return currentStreamingContext !== null;
}

/**
 * Get the conversation ID of the current streaming context, if any.
 * Used to determine if we should clean up the context when switching conversations.
 */
export function getStreamingContextConversationId(): string | null {
  return currentStreamingContext?.conversationId ?? null;
}

/**
 * Get the current streaming message element, if any.
 * This is the single source of truth for the streaming element.
 * @param conversationId - Optional: only return element if it matches this conversation
 */
export function getStreamingMessageElement(conversationId?: string): HTMLElement | null {
  if (!currentStreamingContext) return null;
  if (conversationId && currentStreamingContext.conversationId !== conversationId) return null;
  return currentStreamingContext.element;
}

/**
 * Restore a streaming message UI when switching back to a conversation with an active stream.
 * This re-creates the streaming message element with the accumulated content and thinking state.
 * @param conversationId - The ID of the conversation this streaming message belongs to
 * @param content - The accumulated content so far
 * @param thinkingState - The thinking state to restore
 */
export function restoreStreamingMessage(conversationId: string, content: string, thinkingState?: ThinkingState): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  // Clean up any existing streaming context first (this shouldn't happen normally
  // since switchToConversation should only clean up when switching to a different conversation)
  cleanupStreamingContext();

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';

  // Create thinking indicator with the restored state
  const thinkingIndicator = createThinkingIndicator();
  const restoredThinkingState = thinkingState ?? createThinkingState();

  messageEl.innerHTML = `
    <div class="message-avatar">${AI_AVATAR}</div>
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

    // Render existing content if any
    if (content) {
      contentEl.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';
      // Re-insert thinking indicator at the top
      contentEl.insertBefore(thinkingIndicator, contentEl.firstChild);
    }
  }

  // Check if user is at bottom BEFORE adding the message
  const wasAtBottom = isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX);

  // Store context for updates
  currentStreamingContext = {
    element: messageEl,
    thinkingIndicator,
    thinkingState: restoredThinkingState,
    shouldAutoScroll: wasAtBottom,
    scrollListenerCleanup: null,
    conversationId,
  };

  // Update thinking indicator with the restored state
  updateThinkingIndicator(thinkingIndicator, restoredThinkingState);

  container.appendChild(messageEl);
  programmaticScrollToBottom(container);

  // Reset previousScrollTop to current position AFTER scroll completes
  // This prevents the first scroll event after restore from incorrectly detecting "user scrolled up"
  requestAnimationFrame(() => {
    previousScrollTop = container.scrollTop;
  });

  // Set up scroll listener
  setupStreamingScrollListener(container);

  // Update button visibility
  requestAnimationFrame(() => {
    checkScrollButtonVisibility();
  });

  log.debug('Restored streaming message', { contentLength: content.length, hasThinkingState: !!thinkingState });

  return messageEl;
}

/**
 * Auto-scroll to keep the thinking indicator visible during streaming.
 * Only scrolls if auto-scroll is enabled (controlled by the scroll listener).
 *
 * Note: We CANNOT check isScrolledToBottom() here because when new content is added,
 * scrollHeight increases, making the user appear "not at bottom" even though they
 * never scrolled. The scroll listener handles detecting actual user scrolls by
 * checking scroll direction (scrollTop decreasing = user scrolled up).
 *
 * However, we DO check if scrollTop has decreased since last check to catch cases
 * where the user scrolled up but the scroll event hasn't fired yet (race condition).
 *
 * IMPORTANT: Both this function and setupStreamingScrollListener() can detect user
 * scroll-up. Both MUST call setStreamingPausedIndicator() to keep the visual state
 * consistent with shouldAutoScroll.
 */
function autoScrollForStreaming(): void {
  if (!currentStreamingContext?.shouldAutoScroll) return;

  const messagesContainer = getElementById('messages');
  if (!messagesContainer) return;

  // Synchronous check: if scrollTop has decreased, user scrolled up
  // This catches race conditions where user scrolls up but scroll event hasn't fired yet
  const currentScrollTop = messagesContainer.scrollTop;
  if (currentScrollTop < previousScrollTop) {
    // User scrolled up - disable auto-scroll immediately
    currentStreamingContext.shouldAutoScroll = false;
    log.debug('Streaming auto-scroll paused (detected user scroll up synchronously)');

    // Show visual indicator on scroll button (same as scroll handler)
    setStreamingPausedIndicator(true);

    previousScrollTop = currentScrollTop;
    return;
  }

  // Update previousScrollTop before scrolling (scrollToBottom will increase it)
  previousScrollTop = currentScrollTop;

  scrollToBottom(messagesContainer);
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
 * @param metadata Optional metadata from backend for display (label, icon)
 */
export function updateStreamingToolStart(
  toolName: string,
  detail?: string,
  metadata?: import('../types/api').ToolMetadata
): void {
  if (!currentStreamingContext) return;

  addToolStartToTrace(currentStreamingContext.thinkingState, toolName, detail, metadata);

  updateThinkingIndicator(
    currentStreamingContext.thinkingIndicator,
    currentStreamingContext.thinkingState
  );

  // Auto-scroll to keep tool indicator visible
  autoScrollForStreaming();
}

/**
 * Update the detail for an active tool (e.g., when streaming args become available)
 * @param toolName The name of the tool
 * @param detail The detail to show (e.g., action, query)
 */
export function updateStreamingToolDetail(toolName: string, detail: string): void {
  if (!currentStreamingContext) return;

  updateToolDetailInTrace(currentStreamingContext.thinkingState, toolName, detail);

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
  role: 'user' | 'assistant' = 'assistant',
  language?: string
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

    // Ensure the streaming paused indicator is cleared
    setStreamingPausedIndicator(false);

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
    const actions = createMessageActions(
      messageId,
      createdAt,
      sources,
      generatedImages,
      role,
      language
    );
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
    <div class="message-avatar">${AI_AVATAR}</div>
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;
  container.appendChild(loading);
  programmaticScrollToBottom(container);
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

/**
 * Update a user message's ID from a temporary ID to the real server ID.
 * This updates the message element and all nested elements that reference the message ID
 * (images, documents, etc.) so that clicking on them fetches from the correct API endpoint.
 *
 * @param tempId - The temporary ID (e.g., "temp-1234567890")
 * @param realId - The real server ID returned after saving the message
 */
export function updateUserMessageId(tempId: string, realId: string): void {
  const messagesContainer = getElementById('messages');
  if (!messagesContainer) return;

  // Find the message element with the temp ID
  const messageEl = messagesContainer.querySelector<HTMLDivElement>(
    `.message.user[data-message-id="${tempId}"]`
  );
  if (!messageEl) {
    log.warn('Could not find user message to update ID', { tempId, realId });
    return;
  }

  // Update the message element itself
  messageEl.dataset.messageId = realId;

  // Update all images that reference this message and enable lightbox
  const images = messageEl.querySelectorAll<HTMLImageElement>(
    `img[data-message-id="${tempId}"]`
  );
  images.forEach((img) => {
    img.dataset.messageId = realId;
    // Remove pending state - lightbox now works
    delete img.dataset.pending;
  });

  // Update all document links and buttons that reference this message
  const docElements = messageEl.querySelectorAll<HTMLElement>(
    `[data-message-id="${tempId}"]`
  );
  docElements.forEach((el) => {
    el.dataset.messageId = realId;
  });

  log.debug('Updated user message ID', { tempId, realId, imageCount: images.length });
}

// =============================================================================
// Older Messages Pagination
// =============================================================================

/** Cleanup function for the older messages scroll listener */
let olderMessagesScrollCleanup: (() => void) | null = null;

/**
 * Set up a scroll listener to load older messages when user scrolls near the top.
 * Should be called after rendering messages for a conversation.
 * @param conversationId - The ID of the current conversation
 */
export function setupOlderMessagesScrollListener(conversationId: string): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Clean up any existing listener first
  cleanupOlderMessagesScrollListener();

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = (): void => {
    // Debounce the scroll handler
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = setTimeout(() => {
      const store = useStore.getState();

      // Don't load older messages during active streaming
      // This prevents interference with streaming auto-scroll behavior
      if (store.streamingConversationId === conversationId) {
        return;
      }

      const pagination = store.getMessagesPagination(conversationId);

      // Don't load more if already loading or no more older messages
      if (!pagination || pagination.isLoadingOlder || !pagination.hasOlder) {
        return;
      }

      // Check if user is near the top
      const scrollTop = container.scrollTop;

      if (scrollTop < LOAD_OLDER_MESSAGES_THRESHOLD_PX) {
        loadOlderMessages(conversationId, container);
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  container.addEventListener('scroll', handleScroll, { passive: true });

  // Store cleanup function
  olderMessagesScrollCleanup = () => {
    container.removeEventListener('scroll', handleScroll);
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };

  log.debug('Older messages scroll listener set up', { conversationId });
}

/**
 * Clean up the older messages scroll listener.
 * Should be called when switching conversations or unmounting.
 */
export function cleanupOlderMessagesScrollListener(): void {
  if (olderMessagesScrollCleanup) {
    olderMessagesScrollCleanup();
    olderMessagesScrollCleanup = null;
    log.debug('Older messages scroll listener cleaned up');
  }
}

/**
 * Load older messages for a conversation and prepend them to the UI.
 */
async function loadOlderMessages(conversationId: string, container: HTMLElement): Promise<void> {
  const store = useStore.getState();

  // Guard: Only load if this is still the current conversation
  // This prevents race conditions where the scroll listener fires after
  // the user has already switched to a different conversation
  if (store.currentConversation?.id !== conversationId) {
    log.debug('Skipping older messages load - conversation changed', {
      requestedId: conversationId,
      currentId: store.currentConversation?.id,
    });
    return;
  }

  const pagination = store.getMessagesPagination(conversationId);

  if (!pagination || !pagination.hasOlder || pagination.isLoadingOlder) {
    return;
  }

  log.debug('Loading older messages', { conversationId, cursor: pagination.olderCursor });

  // Set loading state
  store.setLoadingOlderMessages(conversationId, true);

  // Show loading indicator at top
  showOlderMessagesLoader(container);

  // Record the current scroll height and position to maintain scroll position after prepending
  const previousScrollHeight = container.scrollHeight;

  try {
    const result = await conversations.getMessages(
      conversationId,
      undefined, // use default limit
      pagination.olderCursor,
      PaginationDirection.OLDER
    );

    // Guard again after async operation - user might have switched conversations
    if (store.currentConversation?.id !== conversationId) {
      log.debug('Discarding older messages - conversation changed during load', {
        requestedId: conversationId,
        currentId: store.currentConversation?.id,
      });
      store.setLoadingOlderMessages(conversationId, false);
      hideOlderMessagesLoader();
      return;
    }

    // Update store with new messages prepended
    store.prependMessages(conversationId, result.messages, result.pagination);

    // Prepend messages to the UI
    prependMessagesToUI(result.messages, container);

    // Restore scroll position so the user stays at the same place
    // After prepending, scrollHeight increases, so we need to adjust scrollTop
    // We also need to track image loads and re-adjust after images load to prevent drift
    requestAnimationFrame(() => {
      const newScrollHeight = container.scrollHeight;
      const scrollHeightDiff = newScrollHeight - previousScrollHeight;
      const targetScrollTop = container.scrollTop + scrollHeightDiff;
      container.scrollTop = targetScrollTop;

      // Track images in the prepended batch and re-adjust scroll position after they load
      // This prevents scroll drift when lazy-loaded images change the scrollHeight
      trackPrependedImagesForScrollAdjustment(container, targetScrollTop);
    });

    log.info('Loaded older messages', {
      conversationId,
      count: result.messages.length,
      hasOlder: result.pagination.has_older,
    });
  } catch (error) {
    log.error('Failed to load older messages', { error, conversationId });
    // Reset loading state on error
    store.setLoadingOlderMessages(conversationId, false);
  } finally {
    hideOlderMessagesLoader();
  }
}

/**
 * Show a loading indicator at the top of the messages container.
 * For planner view, inserts after the dashboard element to keep it as first element.
 */
function showOlderMessagesLoader(container: HTMLElement): void {
  // Remove any existing loader
  hideOlderMessagesLoader();

  const loader = document.createElement('div');
  loader.className = 'older-messages-loader';
  loader.innerHTML = `
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;

  // Check if there's a dashboard element (planner view)
  const dashboard = container.querySelector('.planner-dashboard-message');
  if (dashboard && dashboard.nextSibling) {
    // Insert after dashboard to keep it as first element
    container.insertBefore(loader, dashboard.nextSibling);
  } else {
    // Normal insertion at the beginning
    container.insertBefore(loader, container.firstChild);
  }
}

/**
 * Hide the older messages loading indicator.
 */
function hideOlderMessagesLoader(): void {
  const loader = document.querySelector('.older-messages-loader');
  loader?.remove();
}

/**
 * Prepend messages to the UI at the top of the messages container.
 * Uses addMessageToUI for each message to avoid code duplication.
 * @param messages - Messages to prepend (should be in chronological order, oldest first)
 * @param container - The messages container element
 */
function prependMessagesToUI(messages: Message[], container: HTMLElement): void {
  if (messages.length === 0) return;

  // Find the first message element (skip loaders/welcome messages)
  const firstMessage = container.querySelector('.message');

  // Add messages in chronological order, each one inserted before the first existing message
  // This maintains chronological order: oldest prepended message ends up first
  messages.forEach((msg) => {
    // Create a temporary container to hold the new message
    const tempContainer = document.createElement('div');
    addMessageToUI(msg, tempContainer);
    const messageEl = tempContainer.firstElementChild;

    if (messageEl) {
      if (firstMessage) {
        // Insert before the first existing message
        container.insertBefore(messageEl, firstMessage);
      } else {
        // No messages yet, just append
        container.appendChild(messageEl);
      }
    }
  });

  // Observe any new images for lazy loading
  const newImages = container.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]:not([src])'
  );
  newImages.forEach((img) => {
    observeThumbnail(img);
  });

  log.debug('Prepended messages to UI', { count: messages.length });
}

/**
 * Track images in prepended messages and re-adjust scroll position after they load.
 * This prevents scroll drift when lazy-loaded images change the scrollHeight.
 *
 * @param container - The messages container element
 * @param initialScrollTop - The scroll position to maintain
 */
function trackPrependedImagesForScrollAdjustment(container: HTMLElement, _initialScrollTop: number): void {
  // Find all images that may still be loading (either no src or not complete)
  const images = container.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]'
  );

  if (images.length === 0) return;

  let pendingLoads = 0;
  let previousScrollHeight = container.scrollHeight;

  const adjustScrollPosition = (): void => {
    // Calculate how much the scroll height changed and adjust scroll position
    const currentScrollHeight = container.scrollHeight;
    const heightDiff = currentScrollHeight - previousScrollHeight;
    if (heightDiff !== 0) {
      container.scrollTop = container.scrollTop + heightDiff;
      previousScrollHeight = currentScrollHeight;
    }
  };

  const handleImageLoad = (): void => {
    pendingLoads--;
    // Adjust scroll position after each image loads
    requestAnimationFrame(() => {
      adjustScrollPosition();
    });
  };

  images.forEach((img) => {
    // Skip already-loaded images
    if (img.complete && img.naturalHeight > 0) return;

    pendingLoads++;
    img.addEventListener('load', handleImageLoad, { once: true });
    img.addEventListener('error', handleImageLoad, { once: true });
  });

  // If no images are pending, nothing to do
  if (pendingLoads === 0) {
    log.debug('No pending images in prepended batch');
  } else {
    log.debug('Tracking prepended images for scroll adjustment', { pendingLoads });
  }
}

// =============================================================================
// Newer Messages Pagination
// =============================================================================

/** Cleanup function for the newer messages scroll listener */
let newerMessagesScrollCleanup: (() => void) | null = null;

/**
 * Set up a scroll listener to load newer messages when user scrolls near the bottom.
 * Used after navigating to a search result in the middle of conversation history.
 * Should be called after loading messages with around_message_id.
 * @param conversationId - The ID of the current conversation
 */
export function setupNewerMessagesScrollListener(conversationId: string): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Clean up any existing listener first
  cleanupNewerMessagesScrollListener();

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = (): void => {
    // Debounce the scroll handler
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = setTimeout(() => {
      const store = useStore.getState();

      // Don't load newer messages during active streaming
      // This prevents interference with streaming auto-scroll behavior
      if (store.streamingConversationId === conversationId) {
        return;
      }

      const pagination = store.getMessagesPagination(conversationId);

      // Don't load more if already loading or no more newer messages
      if (!pagination || pagination.isLoadingNewer || !pagination.hasNewer) {
        return;
      }

      // Check if user is near the bottom
      const scrollTop = container.scrollTop;
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

      if (distanceFromBottom < LOAD_NEWER_MESSAGES_THRESHOLD_PX) {
        loadNewerMessages(conversationId, container);
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  container.addEventListener('scroll', handleScroll, { passive: true });

  // Store cleanup function
  newerMessagesScrollCleanup = () => {
    container.removeEventListener('scroll', handleScroll);
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };

  log.debug('Newer messages scroll listener set up', { conversationId });
}

/**
 * Clean up the newer messages scroll listener.
 * Should be called when switching conversations or unmounting.
 */
export function cleanupNewerMessagesScrollListener(): void {
  if (newerMessagesScrollCleanup) {
    newerMessagesScrollCleanup();
    newerMessagesScrollCleanup = null;
    log.debug('Newer messages scroll listener cleaned up');
  }
}

/**
 * Load newer messages for a conversation and append them to the UI.
 */
async function loadNewerMessages(conversationId: string, container: HTMLElement): Promise<void> {
  const store = useStore.getState();

  // Guard: Only load if this is still the current conversation
  // This prevents race conditions where the scroll listener fires after
  // the user has already switched to a different conversation
  if (store.currentConversation?.id !== conversationId) {
    log.debug('Skipping newer messages load - conversation changed', {
      requestedId: conversationId,
      currentId: store.currentConversation?.id,
    });
    return;
  }

  const pagination = store.getMessagesPagination(conversationId);

  if (!pagination || !pagination.hasNewer || pagination.isLoadingNewer) {
    return;
  }

  log.debug('Loading newer messages', { conversationId, cursor: pagination.newerCursor });

  // Set loading state
  store.setLoadingNewerMessages(conversationId, true);

  // Show loading indicator at bottom
  showNewerMessagesLoader(container);

  try {
    const result = await conversations.getMessages(
      conversationId,
      undefined, // use default limit
      pagination.newerCursor,
      PaginationDirection.NEWER
    );

    // Guard again after async operation - user might have switched conversations
    if (store.currentConversation?.id !== conversationId) {
      log.debug('Discarding newer messages - conversation changed during load', {
        requestedId: conversationId,
        currentId: store.currentConversation?.id,
      });
      store.setLoadingNewerMessages(conversationId, false);
      hideNewerMessagesLoader();
      return;
    }

    // Update store with new messages appended
    store.appendMessages(conversationId, result.messages, result.pagination);

    // Append messages to the UI
    appendMessagesToUI(result.messages, container);

    log.info('Loaded newer messages', {
      conversationId,
      count: result.messages.length,
      hasNewer: result.pagination.has_newer,
    });
  } catch (error) {
    log.error('Failed to load newer messages', { error, conversationId });
    // Reset loading state on error
    store.setLoadingNewerMessages(conversationId, false);
  } finally {
    hideNewerMessagesLoader();
  }
}

/**
 * Show a loading indicator at the bottom of the messages container.
 */
function showNewerMessagesLoader(container: HTMLElement): void {
  // Remove any existing loader
  hideNewerMessagesLoader();

  const loader = document.createElement('div');
  loader.className = 'newer-messages-loader';
  loader.innerHTML = `
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;

  // Insert at the end of the container
  container.appendChild(loader);
}

/**
 * Hide the newer messages loading indicator.
 */
function hideNewerMessagesLoader(): void {
  const loader = document.querySelector('.newer-messages-loader');
  loader?.remove();
}

/**
 * Append messages to the UI at the bottom of the messages container.
 * Uses addMessageToUI for each message to avoid code duplication.
 * @param messages - Messages to append (should be in chronological order, oldest first)
 * @param container - The messages container element
 */
function appendMessagesToUI(messages: Message[], container: HTMLElement): void {
  if (messages.length === 0) return;

  // Add messages in chronological order at the end
  messages.forEach((msg) => {
    addMessageToUI(msg, container);
  });

  // Observe any new images for lazy loading
  const newImages = container.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]:not([src])'
  );
  newImages.forEach((img) => {
    observeThumbnail(img);
  });

  log.debug('Appended messages to UI', { count: messages.length });
}

/**
 * Load ALL remaining newer messages for a conversation.
 * Used before sending a message when in a partial view (after search navigation).
 * This ensures there's no gap between existing messages and the new message.
 *
 * @param conversationId - The conversation ID to load messages for
 * @returns Promise that resolves when all newer messages are loaded, or rejects on error
 */
export async function loadAllRemainingNewerMessages(conversationId: string): Promise<void> {
  const store = useStore.getState();
  const container = getElementById<HTMLDivElement>('messages');

  if (!container) {
    throw new Error('Messages container not found');
  }

  let pagination = store.getMessagesPagination(conversationId);

  // Nothing to load if no newer messages
  if (!pagination || !pagination.hasNewer) {
    log.debug('No newer messages to load', { conversationId });
    return;
  }

  log.info('Loading all remaining newer messages before send', { conversationId });

  // Show loading indicator at bottom while loading
  showNewerMessagesLoader(container);

  let totalLoaded = 0;
  const maxBatches = 50; // Safety limit to prevent infinite loops
  let batchCount = 0;

  try {
    while (pagination && pagination.hasNewer && pagination.newerCursor && batchCount < maxBatches) {
      batchCount++;

      // Guard: Check if conversation changed
      if (store.currentConversation?.id !== conversationId) {
        log.debug('Conversation changed during newer messages load', { conversationId });
        throw new Error('Conversation changed');
      }

      const result = await conversations.getMessages(
        conversationId,
        undefined, // use default limit
        pagination.newerCursor,
        PaginationDirection.NEWER
      );

      // Guard again after async operation
      if (store.currentConversation?.id !== conversationId) {
        log.debug('Conversation changed during newer messages load (post-fetch)', { conversationId });
        throw new Error('Conversation changed');
      }

      // Update store with new messages appended
      store.appendMessages(conversationId, result.messages, result.pagination);

      // Append messages to the UI
      appendMessagesToUI(result.messages, container);

      totalLoaded += result.messages.length;

      // Get updated pagination state
      pagination = store.getMessagesPagination(conversationId);

      log.debug('Loaded batch of newer messages', {
        conversationId,
        batchCount,
        batchSize: result.messages.length,
        totalLoaded,
        hasNewer: result.pagination.has_newer,
      });
    }

    if (batchCount >= maxBatches) {
      log.warn('Reached max batches while loading newer messages', { conversationId, maxBatches });
    }

    log.info('Finished loading all newer messages', { conversationId, totalLoaded, batchCount });
  } finally {
    hideNewerMessagesLoader();
  }
}
