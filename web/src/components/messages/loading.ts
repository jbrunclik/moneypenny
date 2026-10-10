/**
 * Loading indicators for messages and conversations.
 */

import { getElementById } from '../../utils/dom';
import { programmaticScrollToBottom } from '../../utils/thumbnails';
import { AI_AVATAR } from '../../utils/icons';
import { anchorTurn } from './turn-anchor';

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
  // A turn awaiting its reply anchors to the top like a streamed one
  // (send-to-top); the reply takes over the reserved space (batch-send.ts)
  const previous = container.lastElementChild;
  container.appendChild(loading);
  if (previous instanceof HTMLElement && previous.matches('.message:not(.assistant)')) {
    anchorTurn(container, previous, loading);
  } else {
    programmaticScrollToBottom(container);
  }
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
