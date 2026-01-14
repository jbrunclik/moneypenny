/**
 * Message action buttons (copy, delete, speak, cost, sources) and their handlers.
 */

import { costs } from '../../api/client';
import { createLogger } from '../../utils/logger';
import {
  SOURCES_ICON,
  SPARKLES_ICON,
  COST_ICON,
  DELETE_ICON,
  SPEAKER_ICON,
  COPY_ICON,
} from '../../utils/icons';
import { formatMessageTime } from './utils';
import type { Source, GeneratedImage } from '../../types/api';

const log = createLogger('messages');

// ============================================================================
// Button Handler Helpers
// ============================================================================

/**
 * Get message ID from DOM, handling temp-to-real ID updates.
 */
function getMessageIdFromDOM(button: HTMLElement, fallbackId: string): string | null {
  const messageEl = button.closest('.message') as HTMLElement;
  if (!messageEl) {
    log.error('Failed to find message element', { fallbackId, button });
    return null;
  }

  const attrValue = messageEl.getAttribute('data-message-id');
  const datasetValue = messageEl.dataset.messageId;
  const currentMessageId = attrValue || datasetValue;

  if (!currentMessageId) {
    log.error('Failed to get message ID from DOM attribute', {
      fallbackId,
      hasAttribute: messageEl.hasAttribute('data-message-id'),
      attrValue,
      datasetValue,
    });
    return null;
  }

  if (currentMessageId.startsWith('temp-')) {
    log.error('Handler still seeing temp ID - DOM not updated?', {
      currentMessageId,
      closureId: fallbackId,
    });
  }

  return currentMessageId;
}

/**
 * Attach delete button handler.
 */
function attachDeleteHandler(actions: HTMLElement, messageId: string): void {
  const btn = actions.querySelector('.message-delete-btn');
  btn?.addEventListener('click', (e) => {
    const currentMessageId = getMessageIdFromDOM(e.currentTarget as HTMLElement, messageId);
    if (!currentMessageId) return;

    log.debug('Deleting message', { messageId: currentMessageId, closureId: messageId });
    window.dispatchEvent(
      new CustomEvent('message:delete', { detail: { messageId: currentMessageId } })
    );
  });
}

/**
 * Attach sources button handler.
 */
function attachSourcesHandler(actions: HTMLElement, sources: Source[]): void {
  const btn = actions.querySelector('.message-sources-btn');
  btn?.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('sources:open', { detail: sources }));
  });
}

/**
 * Attach generated images button handler.
 */
function attachImagegenHandler(
  actions: HTMLElement,
  generatedImages: GeneratedImage[],
  messageId: string
): void {
  const btn = actions.querySelector('.message-imagegen-btn');
  btn?.addEventListener('click', () => {
    const imagesWithMessageId = generatedImages.map((img) => ({
      ...img,
      message_id: messageId,
    }));
    window.dispatchEvent(new CustomEvent('imagegen:open', { detail: imagesWithMessageId }));
  });
}

/**
 * Attach cost button handler.
 */
function attachCostHandler(actions: HTMLElement, messageId: string): void {
  const btn = actions.querySelector('.message-cost-btn');
  btn?.addEventListener('click', async () => {
    try {
      const costData = await costs.getMessageCost(messageId);
      window.dispatchEvent(new CustomEvent('message-cost:open', { detail: costData }));
    } catch (error) {
      log.warn('Failed to fetch message cost', { error, messageId });
    }
  });
}

/**
 * Attach speak button handler.
 */
function attachSpeakHandler(actions: HTMLElement, messageId: string, language?: string): void {
  const btn = actions.querySelector('.message-speak-btn');
  btn?.addEventListener('click', (e) => {
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
        detail: { messageId, content: messageContent.textContent || '', language },
      })
    );
  });
}

// ============================================================================
// Main Function
// ============================================================================

/**
 * Create message actions container with all buttons and handlers.
 */
export function createMessageActions(
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
  const showCostButton = role === 'assistant';
  const showSpeakButton = role === 'assistant' && typeof speechSynthesis !== 'undefined';

  // Build HTML
  actions.innerHTML = `
    ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
    ${hasSources ? `<button class="message-sources-btn" title="View sources (${sources!.length})">${SOURCES_ICON}</button>` : ''}
    ${hasGeneratedImages ? `<button class="message-imagegen-btn" title="View image generation info">${SPARKLES_ICON}</button>` : ''}
    ${showCostButton ? `<button class="message-cost-btn" title="View message cost">${COST_ICON}</button>` : ''}
    ${showSpeakButton ? `<button class="message-speak-btn" title="Read aloud">${SPEAKER_ICON}</button>` : ''}
    <button class="message-delete-btn" title="Delete message">${DELETE_ICON}</button>
    <button class="message-copy-btn" title="Copy message">${COPY_ICON}</button>
  `;

  // Attach handlers
  attachDeleteHandler(actions, messageId);
  if (hasSources) attachSourcesHandler(actions, sources!);
  if (hasGeneratedImages) attachImagegenHandler(actions, generatedImages!, messageId);
  if (showCostButton) attachCostHandler(actions, messageId);
  if (showSpeakButton) attachSpeakHandler(actions, messageId, language);

  return actions;
}
