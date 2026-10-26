/**
 * Message action buttons (copy, delete, speak, cost, sources) and their handlers.
 */

import { costs } from '../../api/costs';
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
  createIconButton,
} from '../../utils/icons';
import { createElement } from '../../utils/dom';
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
  const openCost = async (): Promise<void> => {
    try {
      const costData = await costs.getMessageCost(messageId);
      window.dispatchEvent(new CustomEvent('message-cost:open', { detail: costData }));
    } catch (error) {
      log.warn('Failed to fetch message cost', { error, messageId });
      toast.error('Failed to load message cost.');
    }
  };
  btn?.addEventListener('click', () => {
    void openCost();
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

/** Which optional action buttons a message gets. */
interface ActionButtons {
  sources: Source[] | null;
  generatedImages: GeneratedImage[] | null;
  cost: boolean;
  speak: boolean;
  rerun: boolean;
  edit: boolean;
  saveQuickAction: boolean;
}

function actionButtonsFor(
  role: 'user' | 'assistant',
  sources: Source[] | null | undefined,
  generatedImages: GeneratedImage[] | null | undefined
): ActionButtons {
  const isAssistant = role === 'assistant';
  return {
    sources: sources && sources.length > 0 ? sources : null,
    generatedImages: generatedImages && generatedImages.length > 0 ? generatedImages : null,
    cost: isAssistant,
    speak: isAssistant && typeof speechSynthesis !== 'undefined',
    // Rendered on every assistant/user message; CSS reveals them only where
    // they make sense (regenerate/continue on the LAST assistant message)
    rerun: isAssistant,
    edit: !isAssistant,
    // Only meaningful inside program conversations; CSS hides it elsewhere
    // (body.has-quick-actions), so it is rendered on every user message.
    saveQuickAction: !isAssistant,
  };
}

/** The secondary buttons (collapsed behind the overflow toggle on touch devices). */
function secondaryButtons(timeStr: string, show: ActionButtons): (Node | false)[] {
  return [
    !!timeStr && createElement('span', { class: 'message-time' }, [timeStr]),
    show.rerun && createIconButton({ class: 'message-regenerate-btn', title: 'Regenerate response' }, REFRESH_ICON),
    show.rerun && createIconButton({ class: 'message-continue-btn', title: 'Continue response' }, CONTINUE_ICON),
    show.edit && createIconButton({ class: 'message-edit-btn', title: 'Edit and resend' }, EDIT_ICON),
    show.saveQuickAction &&
      createIconButton({ class: 'message-save-quick-action-btn', title: 'Save as quick action' }, PIN_ICON),
    !!show.sources &&
      createIconButton({ class: 'message-sources-btn', title: `View sources (${show.sources.length})` }, SOURCES_ICON),
    !!show.generatedImages &&
      createIconButton({ class: 'message-imagegen-btn', title: 'View image generation info' }, SPARKLES_ICON),
    show.cost && createIconButton({ class: 'message-cost-btn', title: 'View message cost' }, COST_ICON),
    show.speak && createIconButton({ class: 'message-speak-btn', title: 'Read aloud' }, SPEAKER_ICON),
    createIconButton({ class: 'message-delete-btn', title: 'Delete message' }, DELETE_ICON),
  ];
}

function attachActionHandlers(
  actions: HTMLElement,
  messageId: string,
  show: ActionButtons,
  language: string | undefined
): void {
  attachDeleteHandler(actions, messageId);
  if (show.rerun) attachRerunHandlers(actions, messageId);
  if (show.edit) attachEditHandler(actions, messageId);
  if (show.saveQuickAction) attachSaveQuickActionHandler(actions, messageId);
  if (show.sources) attachSourcesHandler(actions, show.sources);
  if (show.generatedImages) attachImagegenHandler(actions, show.generatedImages, messageId);
  if (show.cost) attachCostHandler(actions, messageId);
  if (show.speak) attachSpeakHandler(actions, messageId, language);
}

/**
 * Create message actions container with all buttons and handlers.
 */
export function createMessageActions(
  messageId: string,
  createdAt: string | undefined,
  sources: Source[] | null | undefined,
  generatedImages: GeneratedImage[] | null | undefined,
  role: 'user' | 'assistant',
  language?: string | null
): HTMLElement {
  const actions = document.createElement('div');
  actions.className = 'message-actions';

  const timeStr = createdAt ? formatMessageTime(createdAt) : '';
  const show = actionButtonsFor(role, sources, generatedImages);

  // Build HTML. On touch devices the secondary buttons collapse behind
  // the overflow toggle (CSS-controlled); copy is the most-used action
  // so it stays always visible next to the toggle. On desktop the
  // overflow toggle is hidden and everything reveals on hover as before.
  actions.append(
    createIconButton({ class: 'message-copy-btn', title: 'Copy message' }, COPY_ICON),
    createElement(
      'button',
      { class: 'message-actions-overflow', 'aria-label': 'Message actions', 'aria-expanded': 'false' },
      ['⋯']
    ),
    createElement('span', { class: 'message-actions-buttons' }, secondaryButtons(timeStr, show))
  );

  attachActionHandlers(actions, messageId, show, language ?? undefined);
  return actions;
}
