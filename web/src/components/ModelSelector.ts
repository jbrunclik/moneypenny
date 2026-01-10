import { escapeHtml, getElementById } from '../utils/dom';
import { useStore } from '../state/store';
import { conversations as conversationsApi } from '../api/client';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import { CHECK_ICON } from '../utils/icons';

const log = createLogger('model-selector');

/**
 * Initialize model selector event handlers
 */
export function initModelSelector(): void {
  const btn = getElementById<HTMLButtonElement>('model-selector-btn');
  const dropdown = getElementById<HTMLDivElement>('model-dropdown');

  if (!btn || !dropdown) return;

  // Toggle dropdown
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleModelDropdown();
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (
      !dropdown.contains(e.target as Node) &&
      !btn.contains(e.target as Node)
    ) {
      closeModelDropdown();
    }
  });

  // Handle model selection (event delegation)
  dropdown.addEventListener('click', (e) => {
    const option = (e.target as HTMLElement).closest('[data-model-id]');
    if (option) {
      const modelId = (option as HTMLElement).dataset.modelId;
      if (modelId) {
        selectModel(modelId);
      }
    }
  });
}

/**
 * Toggle model dropdown visibility.
 * Re-renders dropdown content when opening to ensure checkmark reflects current model.
 */
function toggleModelDropdown(): void {
  const dropdown = getElementById<HTMLDivElement>('model-dropdown');
  if (!dropdown) return;

  const isHidden = dropdown.classList.contains('hidden');
  if (isHidden) {
    // Re-render dropdown content before showing to ensure checkmark is correct
    renderModelDropdown();
  }
  dropdown.classList.toggle('hidden');
}

/**
 * Close model dropdown
 */
function closeModelDropdown(): void {
  const dropdown = getElementById<HTMLDivElement>('model-dropdown');
  dropdown?.classList.add('hidden');
}

/**
 * Check if a conversation ID is temporary (not yet saved to DB)
 */
function isTempConversation(convId: string): boolean {
  return convId.startsWith('temp-');
}

/**
 * Select a model
 */
async function selectModel(modelId: string): Promise<void> {
  const store = useStore.getState();
  const { currentConversation, models } = store;

  // Get the model to display
  const model = models.find((m) => m.id === modelId);
  if (!model) return;

  // Get previous model for rollback
  const previousModelId = currentConversation?.model || store.pendingModel || store.defaultModel;
  const previousModel = models.find((m) => m.id === previousModelId);

  // Update UI immediately (optimistic update) - show short name in button
  updateCurrentModelDisplay(model.short_name);
  closeModelDropdown();

  // If no conversation exists, store as pending model
  if (!currentConversation) {
    store.setPendingModel(modelId);
    log.debug('Set pending model (no conversation)', { modelId });
    return;
  }

  // For temp conversations (not yet persisted), just update locally
  // The model will be used when the conversation is created on first message
  if (isTempConversation(currentConversation.id)) {
    store.updateConversation(currentConversation.id, { model: modelId });
    log.debug('Updated model for temp conversation', { modelId, conversationId: currentConversation.id });
    return;
  }

  // For persisted conversations, update on server
  try {
    await conversationsApi.update(currentConversation.id, { model: modelId });
    store.updateConversation(currentConversation.id, { model: modelId });
  } catch (error) {
    log.error('Failed to update model', { error, modelId, conversationId: currentConversation.id });
    // Revert optimistic update on failure
    if (previousModel) {
      updateCurrentModelDisplay(previousModel.short_name);
    }
    toast.error('Failed to change model. Please try again.');
  }
}

/**
 * Update current model display text (shows short name in button)
 */
function updateCurrentModelDisplay(shortName: string): void {
  const display = getElementById<HTMLSpanElement>('current-model-name');
  if (display) {
    display.textContent = shortName;
  }
}

/**
 * Render model dropdown options
 */
export function renderModelDropdown(): void {
  const dropdown = getElementById<HTMLDivElement>('model-dropdown');
  if (!dropdown) return;

  const { models, currentConversation, pendingModel, defaultModel } = useStore.getState();
  // Priority: conversation model > pending model > default model
  const currentModelId = currentConversation?.model || pendingModel || defaultModel;

  dropdown.innerHTML = models
    .map(
      (model) => `
      <div class="model-option ${model.id === currentModelId ? 'selected' : ''}"
           data-model-id="${model.id}"
           data-short-name="${escapeHtml(model.short_name)}">
        <span class="model-name">${escapeHtml(model.name)}</span>
        ${model.id === currentModelId ? `<span class="model-check">${CHECK_ICON}</span>` : ''}
      </div>
    `
    )
    .join('');

  // Update current model display (show short name in button)
  const currentModel = models.find((m) => m.id === currentModelId);
  if (currentModel) {
    updateCurrentModelDisplay(currentModel.short_name);
  }
}