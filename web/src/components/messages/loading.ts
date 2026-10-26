/**
 * Loading indicators for messages and conversations.
 */

import { createElement, getElementById } from '../../utils/dom';
import { programmaticScrollToBottom } from '../../utils/programmatic-scroll';
import { AI_AVATAR, createIconElement } from '../../utils/icons';
import { anchorTurn } from './turn-anchor';

/**
 * Show loading indicator in messages
 * @param awaitingUpload - Attachments are still uploading: the loader is
 *   invisible (but keeps its box - the reserved send-to-top space) until
 *   revealLoadingIndicator(), like the streamed bubble's `awaiting-upload`
 */
export function showLoadingIndicator(awaitingUpload = false): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Remove existing loading indicator
  hideLoadingIndicator();

  const loading = document.createElement('div');
  loading.className = 'message-loading';
  loading.classList.toggle('awaiting-upload', awaitingUpload);
  loading.append(
    createIconElement('message-avatar', AI_AVATAR, 'div'),
    createElement('div', { class: 'loading-dots' }, [
      createElement('span'),
      createElement('span'),
      createElement('span'),
    ])
  );
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

/** The upload is done and the server is working: show the loader's dots. */
export function revealLoadingIndicator(): void {
  document.querySelector('.message-loading')?.classList.remove('awaiting-upload');
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
