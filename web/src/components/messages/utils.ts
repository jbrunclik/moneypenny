/**
 * Shared utility functions for the Messages component.
 */

import { getElementById } from '../../utils/dom';
import { createLogger } from '../../utils/logger';

const log = createLogger('messages');

/**
 * Format a timestamp for display using system locale
 * Shows time for today, "Yesterday HH:MM" for yesterday, or locale date + time for older
 */
export function formatMessageTime(isoString: string): string {
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

  // Check if element with real ID already exists (idempotent - already updated)
  const existingEl = messagesContainer.querySelector<HTMLDivElement>(
    `.message.user[data-message-id="${realId}"]`
  );
  if (existingEl) {
    // Already updated, nothing to do
    return;
  }

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
