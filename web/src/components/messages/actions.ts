/**
 * Message action buttons (copy, delete, speak, cost, sources) and their handlers.
 */

import { costs } from '../../api/client';
import { toast } from '../Toast';
import { createLogger } from '../../utils/logger';
import {
  SOURCES_ICON,
  SPARKLES_ICON,
  COST_ICON,
  CONTINUE_ICON,
  DELETE_ICON,
  EDIT_ICON,
  PIN_ICON,
  REFRESH_ICON,
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
      toast.error('Failed to load message cost.');
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

/**
 * Regenerate / continue: dispatched as document events so core/messaging can
 * own the flow without an import cycle (this module is imported by render).
 */
function attachRerunHandlers(actions: HTMLElement, messageId: string): void {
  actions.querySelector('.message-regenerate-btn')?.addEventListener('click', () => {
    document.dispatchEvent(new CustomEvent('message:regenerate', { detail: { messageId } }));
  });
  actions.querySelector('.message-continue-btn')?.addEventListener('click', () => {
    document.dispatchEvent(new CustomEvent('message:continue', { detail: { messageId } }));
  });
}

function attachEditHandler(actions: HTMLElement, messageId: string): void {
  actions.querySelector('.message-edit-btn')?.addEventListener('click', () => {
    document.dispatchEvent(new CustomEvent('message:edit', { detail: { messageId } }));
  });
}

function attachSaveQuickActionHandler(actions: HTMLElement, messageId: string): void {
  actions.querySelector('.message-save-quick-action-btn')?.addEventListener('click', () => {
    document.dispatchEvent(
      new CustomEvent('message:save-quick-action', { detail: { messageId } })
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
  // Rendered on every assistant/user message; CSS reveals them only where
  // they make sense (regenerate/continue on the LAST assistant message)
  const showRerunButtons = role === 'assistant';
  const showEditButton = role === 'user';
  // Only meaningful inside program conversations; CSS hides it elsewhere
  // (body.has-quick-actions), so it is rendered on every user message.
  const showSaveQuickActionButton = role === 'user';

  // Build HTML. On touch devices the secondary buttons collapse behind
  // the overflow toggle (CSS-controlled); copy is the most-used action
  // so it stays always visible next to the toggle. On desktop the
  // overflow toggle is hidden and everything reveals on hover as before.
  actions.innerHTML = `
    <button class="message-copy-btn" title="Copy message">${COPY_ICON}</button>
    <button class="message-actions-overflow" aria-label="Message actions" aria-expanded="false">⋯</button>
    <span class="message-actions-buttons">
      ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
      ${showRerunButtons ? `<button class="message-regenerate-btn" title="Regenerate response">${REFRESH_ICON}</button>` : ''}
      ${showRerunButtons ? `<button class="message-continue-btn" title="Continue response">${CONTINUE_ICON}</button>` : ''}
      ${showEditButton ? `<button class="message-edit-btn" title="Edit and resend">${EDIT_ICON}</button>` : ''}
      ${showSaveQuickActionButton ? `<button class="message-save-quick-action-btn" title="Save as quick action">${PIN_ICON}</button>` : ''}
      ${hasSources ? `<button class="message-sources-btn" title="View sources (${sources!.length})">${SOURCES_ICON}</button>` : ''}
      ${hasGeneratedImages ? `<button class="message-imagegen-btn" title="View image generation info">${SPARKLES_ICON}</button>` : ''}
      ${showCostButton ? `<button class="message-cost-btn" title="View message cost">${COST_ICON}</button>` : ''}
      ${showSpeakButton ? `<button class="message-speak-btn" title="Read aloud">${SPEAKER_ICON}</button>` : ''}
      <button class="message-delete-btn" title="Delete message">${DELETE_ICON}</button>
    </span>
  `;

  // Attach handlers
  attachDeleteHandler(actions, messageId);
  if (showRerunButtons) attachRerunHandlers(actions, messageId);
  if (showEditButton) attachEditHandler(actions, messageId);
  if (showSaveQuickActionButton) attachSaveQuickActionHandler(actions, messageId);
  if (hasSources) attachSourcesHandler(actions, sources!);
  if (hasGeneratedImages) attachImagegenHandler(actions, generatedImages!, messageId);
  if (showCostButton) attachCostHandler(actions, messageId);
  if (showSpeakButton) attachSpeakHandler(actions, messageId, language);

  return actions;
}
