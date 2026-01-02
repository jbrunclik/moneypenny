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
 * Handle Escape key press - close the topmost visible popup.
 */
function handleEscapeKey(e: KeyboardEvent): void {
  if (e.key !== 'Escape') return;

  // Find visible popups (iterate in reverse to handle most recently registered first)
  for (let i = handlers.length - 1; i >= 0; i--) {
    const { popupId, onEscape } = handlers[i];
    const popup = document.getElementById(popupId);

    if (popup && !popup.classList.contains('hidden')) {
      log.debug('Escape key closing popup', { popupId });
      onEscape();
      e.preventDefault();
      e.stopPropagation();
      return; // Only close one popup at a time
    }
  }
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
