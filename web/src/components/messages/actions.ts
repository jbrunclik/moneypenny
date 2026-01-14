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

/**
 * Create message actions container with all buttons and handlers.
 * This centralizes the logic for creating message action buttons (sources, imagegen, cost, speak, delete, copy)
 * to avoid duplication between addMessageToUI() and finalizeStreamingMessage().
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
