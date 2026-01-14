/**
 * Message rendering - HTML generation for individual messages and message lists.
 */

import { escapeHtml, getElementById, scrollToBottom, clearElement } from '../../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../../utils/markdown';
import { linkifyText } from '../../utils/linkify';
import {
  observeThumbnail,
  markProgrammaticScrollStart,
  markProgrammaticScrollEnd,
  countVisibleImagesForScroll,
  setDeferImageObservation,
} from '../../utils/thumbnails';
import { createUserAvatarElement } from '../../utils/avatar';
import { checkScrollButtonVisibility } from '../ScrollToBottom';
import { AI_AVATAR } from '../../utils/icons';
import { useStore } from '../../state/store';
import { createLogger } from '../../utils/logger';
import { createMessageActions } from './actions';
import { renderMessageFiles } from './attachments';
import type { RenderMessagesOptions } from './types';
import type { Message } from '../../types/api';

const log = createLogger('messages');

/**
 * Render all messages in the container
 */
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
