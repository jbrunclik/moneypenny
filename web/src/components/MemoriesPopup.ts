import { getElementById, escapeHtml } from '../utils/dom';
import { BRAIN_ICON, CLOSE_ICON, DELETE_ICON } from '../utils/icons';
import { memories } from '../api/client';
import type { Memory } from '../types/api';
import { toast } from './Toast';
import { showConfirm } from './Modal';
import { createLogger } from '../utils/logger';

const log = createLogger('memories-popup');

const POPUP_ID = 'memories-popup';
const MEMORY_LIMIT = 100;

/** Category colors and labels */
const CATEGORY_CONFIG: Record<string, { label: string; class: string }> = {
  preference: { label: 'Preference', class: 'preference' },
  fact: { label: 'Fact', class: 'fact' },
  context: { label: 'Context', class: 'context' },
  goal: { label: 'Goal', class: 'goal' },
};

/** Current memories data */
let currentMemories: Memory[] = [];

/**
 * Format relative time (e.g., "2 days ago")
 */
function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);
  const diffWeeks = Math.floor(diffDays / 7);
  const diffMonths = Math.floor(diffDays / 30);

  if (diffSeconds < 60) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes} minute${diffMinutes === 1 ? '' : 's'} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
  if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
  if (diffWeeks < 4) return `${diffWeeks} week${diffWeeks === 1 ? '' : 's'} ago`;
  return `${diffMonths} month${diffMonths === 1 ? '' : 's'} ago`;
}

/**
 * Render a single memory item
 */
function renderMemoryItem(memory: Memory): string {
  const categoryConfig = memory.category ? CATEGORY_CONFIG[memory.category] : null;
  const categoryBadge = categoryConfig
    ? `<span class="memory-category ${categoryConfig.class}">${escapeHtml(categoryConfig.label)}</span>`
    : '';

  return `
    <div class="memory-item" data-memory-id="${escapeHtml(memory.id)}">
      <div class="memory-header">
        ${categoryBadge}
        <span class="memory-time">${formatRelativeTime(memory.updated_at)}</span>
      </div>
      <div class="memory-content">${escapeHtml(memory.content)}</div>
      <button class="memory-delete-btn" data-memory-id="${escapeHtml(memory.id)}" aria-label="Delete memory">
        ${DELETE_ICON}
      </button>
    </div>
  `;
}

/**
 * Render the popup content
 */
function renderContent(memoriesList: Memory[]): string {
  if (memoriesList.length === 0) {
    return `
      <div class="memories-empty">
        <div class="memories-empty-icon">${BRAIN_ICON}</div>
        <p>No memories yet.</p>
        <p class="text-muted">The AI will learn about you as you chat.</p>
      </div>
    `;
  }

  // Sort by updated_at descending (most recent first)
  const sorted = [...memoriesList].sort((a, b) =>
    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  );

  return `
    <div class="memories-list">
      ${sorted.map(renderMemoryItem).join('')}
    </div>
  `;
}

/**
 * Update the popup body content
 */
function updatePopupContent(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  const body = popup?.querySelector('.info-popup-body');
  const footer = popup?.querySelector('.info-popup-footer');

  if (body) {
    body.innerHTML = renderContent(currentMemories);
  }

  if (footer) {
    footer.innerHTML = `<span class="memories-count">${currentMemories.length}/${MEMORY_LIMIT} memories</span>`;
  }
}

/**
 * Handle delete button click
 */
async function handleDelete(memoryId: string): Promise<void> {
  // Find the memory content for the confirmation message
  const memory = currentMemories.find(m => m.id === memoryId);
  const contentPreview = memory ? memory.content.slice(0, 50) + (memory.content.length > 50 ? '...' : '') : '';

  const confirmed = await showConfirm({
    title: 'Delete Memory',
    message: `Are you sure you want to delete this memory?\n\n"${contentPreview}"`,
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
  });

  if (!confirmed) {
    return;
  }

  log.debug('Deleting memory', { memoryId });

  try {
    await memories.delete(memoryId);

    // Remove from current list and update UI
    currentMemories = currentMemories.filter(m => m.id !== memoryId);
    updatePopupContent();

    toast.success('Memory deleted');
    log.info('Memory deleted', { memoryId });
  } catch (error) {
    log.error('Failed to delete memory', { memoryId, error });
    toast.error('Failed to delete memory');
  }
}

/**
 * Open the memories popup
 */
export async function openMemoriesPopup(): Promise<void> {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Show popup with loading state
  const content = popup.querySelector('.info-popup-content');
  if (content) {
    content.innerHTML = `
      <div class="info-popup-header">
        <span class="info-popup-icon">${BRAIN_ICON}</span>
        <h3>Memories</h3>
        <button class="info-popup-close" aria-label="Close">${CLOSE_ICON}</button>
      </div>
      <div class="info-popup-body memories-body">
        <div class="memories-loading">Loading memories...</div>
      </div>
      <div class="info-popup-footer">
        <span class="memories-count">-/- memories</span>
      </div>
    `;

    // Attach close handler
    content.querySelector('.info-popup-close')?.addEventListener('click', closeMemoriesPopup);
  }

  popup.classList.remove('hidden');

  // Fetch memories
  try {
    log.debug('Fetching memories');
    currentMemories = await memories.list();
    log.info('Memories loaded', { count: currentMemories.length });
    updatePopupContent();
  } catch (error) {
    log.error('Failed to load memories', { error });
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.innerHTML = `
        <div class="memories-error">
          <p>Failed to load memories.</p>
          <button class="btn btn-secondary memories-retry-btn">Retry</button>
        </div>
      `;
    }
  }
}

/**
 * Close the memories popup
 */
export function closeMemoriesPopup(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (popup) {
    popup.classList.add('hidden');
  }
}

/**
 * Initialize memories popup
 */
export function initMemoriesPopup(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Close on backdrop click
  popup.addEventListener('click', (e) => {
    if (e.target === popup) {
      closeMemoriesPopup();
    }
  });

  // Close on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !popup.classList.contains('hidden')) {
      closeMemoriesPopup();
    }
  });

  // Event delegation for delete buttons and retry
  popup.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;

    // Delete button
    const deleteBtn = target.closest('.memory-delete-btn') as HTMLElement;
    if (deleteBtn) {
      const memoryId = deleteBtn.dataset.memoryId;
      if (memoryId) {
        handleDelete(memoryId);
      }
      return;
    }

    // Retry button
    if (target.classList.contains('memories-retry-btn')) {
      openMemoriesPopup();
    }
  });

  log.debug('Memories popup initialized');
}

/**
 * Get HTML for memories popup shell
 */
export function getMemoriesPopupHtml(): string {
  return `
    <div id="${POPUP_ID}" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>
  `;
}
