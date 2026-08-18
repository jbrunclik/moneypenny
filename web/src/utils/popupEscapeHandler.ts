/**
 * Centralized Escape key handler for all popups.
 *
 * This module consolidates multiple document-level keydown listeners into a single
 * listener that handles Escape key for all registered popups. This is more efficient
 * than having separate listeners per popup (5+ listeners → 1 listener).
 *
 * Note: Modal.ts has its own handler because it also needs Enter and Tab handling
 * for focus trapping. This handler is specifically for simple Escape-to-close popups.
 *
 * Usage:
 *   import { registerPopupEscapeHandler, initPopupEscapeListener } from './utils/popupEscapeHandler';
 *
 *   // Register a popup during init
 *   registerPopupEscapeHandler('my-popup-id', () => closeMyPopup());
 *
 *   // Initialize the single listener once in main.ts
 *   initPopupEscapeListener();
 */

import { createLogger } from './logger';
import { trapTabKey } from './focus-trap';

const log = createLogger('popup-escape');

interface PopupHandler {
  popupId: string;
  onEscape: () => void;
}

// Registry of popup handlers
const handlers: PopupHandler[] = [];

// Track if listener is initialized
let isInitialized = false;

/**
 * Register a popup to be closed on Escape key.
 *
 * @param popupId - The DOM element ID of the popup
 * @param onEscape - Callback to close the popup
 * @returns Cleanup function to unregister (useful for dynamic popups)
 */
export function registerPopupEscapeHandler(
  popupId: string,
  onEscape: () => void
): () => void {
  const handler: PopupHandler = { popupId, onEscape };
  handlers.push(handler);

  log.debug('Registered popup escape handler', { popupId });

  // Return cleanup function
  return () => {
    const index = handlers.indexOf(handler);
    if (index > -1) {
      handlers.splice(index, 1);
      log.debug('Unregistered popup escape handler', { popupId });
    }
  };
}

/**
 * Find the topmost visible registered popup (most recently registered first).
 */
function findVisiblePopup(): { popup: HTMLElement; handler: PopupHandler } | null {
  for (let i = handlers.length - 1; i >= 0; i--) {
    const popup = document.getElementById(handlers[i].popupId);
    if (popup && !popup.classList.contains('hidden')) {
      return { popup, handler: handlers[i] };
    }
  }
  return null;
}

/**
 * Handle keydown for open popups: Escape closes the topmost visible
 * popup; Tab is trapped inside it so focus cannot escape to the page.
 */
function handleEscapeKey(e: KeyboardEvent): void {
  if (e.key !== 'Escape' && e.key !== 'Tab') return;

  const visible = findVisiblePopup();
  if (!visible) return;

  if (e.key === 'Tab') {
    trapTabKey(visible.popup, e);
    return;
  }

  log.debug('Escape key closing popup', { popupId: visible.handler.popupId });
  visible.handler.onEscape();
  e.preventDefault();
  e.stopPropagation();
}

/**
 * Initialize the single document-level Escape key listener.
 * Call this once in main.ts during app initialization.
 */
export function initPopupEscapeListener(): void {
  if (isInitialized) {
    log.warn('Popup escape listener already initialized');
    return;
  }

  document.addEventListener('keydown', handleEscapeKey);
  isInitialized = true;

  log.debug('Popup escape listener initialized');
}

/**
 * Remove the Escape key listener (for testing/cleanup).
 */
export function destroyPopupEscapeListener(): void {
  if (!isInitialized) return;

  document.removeEventListener('keydown', handleEscapeKey);
  isInitialized = false;
  handlers.length = 0; // Clear all handlers

  log.debug('Popup escape listener destroyed');
}
