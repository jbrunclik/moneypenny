import { getElementById, clearElement } from '../utils/dom';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';

const log = createLogger('planner-view');

/**
 * Set up the planner view by updating the header.
 * The planner reuses the existing messages container and input area.
 */
export function setupPlannerView(): void {
  log.debug('Setting up planner view');

  // Update header title
  const titleEl = getElementById('current-chat-title');
  if (titleEl) {
    titleEl.textContent = 'Planner';
  }

  // Clear messages container (dashboard and messages will be added separately)
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    clearElement(messagesContainer);
  }

  log.debug('Planner view set up');
}

/**
 * Clear the planner view and restore normal chat view.
 */
export function clearPlannerView(): void {
  log.debug('Clearing planner view');
  useStore.getState().setIsPlannerView(false);
}

/**
 * Check if the planner view is currently active.
 */
export function isPlannerViewActive(): boolean {
  return useStore.getState().isPlannerView;
}

// Legacy exports for compatibility - these are no longer used but kept for gradual migration
export function renderPlannerView(): void {
  setupPlannerView();
}

export function showPlannerMessagesLoading(): void {
  // No-op - loading shown inline in messages
}

export function showPlannerMessagesEmpty(): void {
  // No-op - empty state handled by main.ts
}
