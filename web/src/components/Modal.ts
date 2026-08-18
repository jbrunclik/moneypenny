/**
 * Modal dialog component for alerts, confirmations, and prompts.
 * Replaces native browser dialogs (alert, confirm, prompt) with
 * styled, accessible, keyboard-navigable modals.
 *
 * Usage:
 *   import { showAlert, showConfirm, showPrompt, initModal } from './components/Modal';
 *
 *   // Initialize once on app startup
 *   initModal();
 *
 *   // Alert (OK button only)
 *   await showAlert({ title: 'Error', message: 'Something went wrong.' });
 *
 *   // Confirm (Cancel/OK buttons)
 *   const confirmed = await showConfirm({
 *     title: 'Delete',
 *     message: 'Are you sure?',
 *     confirmLabel: 'Delete',
 *     danger: true
 *   });
 *
 *   // Prompt (input + Cancel/OK buttons)
 *   const value = await showPrompt({
 *     title: 'Rename',
 *     message: 'Enter new name:',
 *     defaultValue: 'Untitled',
 *     placeholder: 'Name'
 *   });
 */

import { escapeHtml } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import { CLOSE_ICON } from '../utils/icons';

// Modal container element
let modalContainer: HTMLDivElement | null = null;

// Current modal state
let currentResolve: ((value: boolean | string | null) => void) | null = null;
let modalType: 'alert' | 'confirm' | 'prompt' = 'alert';

/**
 * Initialize the modal system.
 * Call this once during app initialization.
 */
export function initModal(): void {
  // Create container if it doesn't exist
  if (!modalContainer) {
    modalContainer = document.createElement('div');
    modalContainer.id = 'modal-container';
    modalContainer.className = 'modal-container modal-hidden';
    document.body.appendChild(modalContainer);

    // Handle click events via delegation
    modalContainer.addEventListener('click', handleModalClick);

    // Handle keyboard events
    document.addEventListener('keydown', handleModalKeydown);
  }
}

/**
 * Show an alert modal (OK button only).
 * Returns a promise that resolves when dismissed.
 */
export function showAlert(options: {
  title?: string;
  message: string;
}): Promise<void> {
  return new Promise((resolve) => {
    modalType = 'alert';
    currentResolve = () => resolve();
    renderModal({
      title: options.title,
      message: options.message,
      showCancel: false,
      confirmLabel: 'OK',
    });
    showModalContainer();
  });
}

/**
 * Show a confirm modal (Cancel/Confirm buttons).
 * Returns a promise that resolves to true (confirmed) or false (cancelled).
 */
export function showConfirm(options: {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}): Promise<boolean> {
  return new Promise((resolve) => {
    modalType = 'confirm';
    currentResolve = resolve as (value: boolean | string | null) => void;
    renderModal({
      title: options.title,
      message: options.message,
      showCancel: true,
      confirmLabel: options.confirmLabel || 'OK',
      cancelLabel: options.cancelLabel || 'Cancel',
      danger: options.danger,
    });
    showModalContainer();
  });
}

/**
 * Show a prompt modal (input + Cancel/Confirm buttons).
 * Returns a promise that resolves to the input value, or null if cancelled.
 */
export function showPrompt(options: {
  title?: string;
  message: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
}): Promise<string | null> {
  return new Promise((resolve) => {
    modalType = 'prompt';
    currentResolve = resolve as (value: boolean | string | null) => void;
    renderModal({
      title: options.title,
      message: options.message,
      showCancel: true,
      confirmLabel: options.confirmLabel || 'OK',
      cancelLabel: options.cancelLabel || 'Cancel',
      showInput: true,
      defaultValue: options.defaultValue,
      placeholder: options.placeholder,
    });
    showModalContainer();

    // Focus the input
    setTimeout(() => {
      const input = modalContainer?.querySelector('.modal-input') as HTMLInputElement;
      if (input) {
        input.focus();
        input.select();
      }
    }, 50);
  });
}

/**
 * Close the current modal.
 */
export function closeModal(result: boolean | string | null = null): void {
  if (!modalContainer || !currentResolve) return;

  // Start exit animation
  const modalEl = modalContainer.querySelector('.modal');
  if (modalEl) {
    modalEl.classList.add('modal-exit');
  }
  modalContainer.classList.add('modal-overlay-exit');

  // Resolve and cleanup after animation
  setTimeout(() => {
    hideModalContainer();
    if (currentResolve) {
      currentResolve(result);
      currentResolve = null;
    }
  }, 150); // Match CSS animation duration
}

/**
 * Handle click events on modal elements.
 */
function handleModalClick(e: MouseEvent): void {
  const target = e.target as HTMLElement;

  // Handle overlay click (close modal)
  if (target.classList.contains('modal-container')) {
    if (modalType === 'alert') {
      closeModal();
    } else {
      closeModal(modalType === 'confirm' ? false : null);
    }
    return;
  }

  // Handle close button click
  if (target.closest('.modal-close')) {
    if (modalType === 'alert') {
      closeModal();
    } else {
      closeModal(modalType === 'confirm' ? false : null);
    }
    return;
  }

  // Handle cancel button click
  if (target.closest('.modal-cancel')) {
    closeModal(modalType === 'confirm' ? false : null);
    return;
  }

  // Handle confirm button click
  if (target.closest('.modal-confirm')) {
    if (modalType === 'prompt') {
      const input = modalContainer?.querySelector('.modal-input') as HTMLInputElement;
      closeModal(input?.value ?? '');
    } else {
      closeModal(modalType === 'confirm' ? true : null);
    }
    return;
  }
}

/**
 * Handle keyboard events for modal.
 */
function handleModalKeydown(e: KeyboardEvent): void {
  if (!modalContainer || modalContainer.classList.contains('modal-hidden')) {
    return;
  }

  // Escape to close
  if (e.key === 'Escape') {
    e.preventDefault();
    if (modalType === 'alert') {
      closeModal();
    } else {
      closeModal(modalType === 'confirm' ? false : null);
    }
    return;
  }

  // Enter to confirm
  if (e.key === 'Enter') {
    // Don't interfere with input field (unless it's a single-line input)
    const input = modalContainer.querySelector('.modal-input') as HTMLInputElement;
    if (input && document.activeElement === input) {
      e.preventDefault();
      closeModal(input.value);
      return;
    }

    // Confirm if not focused on cancel button
    if (!document.activeElement?.classList.contains('modal-cancel')) {
      e.preventDefault();
      if (modalType === 'prompt') {
        closeModal(input?.value ?? '');
      } else {
        closeModal(modalType === 'confirm' ? true : null);
      }
    }
    return;
  }

  // Tab for focus trapping
  trapTabKey(modalContainer, e);
}

/**
 * Render the modal content.
 */
function renderModal(options: {
  title?: string;
  message: string;
  showCancel: boolean;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  showInput?: boolean;
  defaultValue?: string;
  placeholder?: string;
}): void {
  if (!modalContainer) return;

  const titleHtml = options.title
    ? `<h2 class="modal-title">${escapeHtml(options.title)}</h2>`
    : '';

  const inputHtml = options.showInput
    ? `<input type="text" class="modal-input" value="${escapeHtml(options.defaultValue || '')}" placeholder="${escapeHtml(options.placeholder || '')}">`
    : '';

  const cancelHtml = options.showCancel
    ? `<button class="modal-cancel">${escapeHtml(options.cancelLabel || 'Cancel')}</button>`
    : '';

  const confirmClass = options.danger ? 'modal-confirm modal-danger' : 'modal-confirm';

  modalContainer.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" ${options.title ? `aria-labelledby="modal-title"` : ''}>
      <button class="modal-close" aria-label="Close">${CLOSE_ICON}</button>
      ${titleHtml}
      <p class="modal-message">${escapeHtml(options.message)}</p>
      ${inputHtml}
      <div class="modal-actions">
        ${cancelHtml}
        <button class="${confirmClass}">${escapeHtml(options.confirmLabel)}</button>
      </div>
    </div>
  `;
}

/**
 * Show the modal container.
 */
function showModalContainer(): void {
  if (!modalContainer) return;
  modalContainer.classList.remove('modal-hidden');

  // Focus first focusable element after layout is complete
  // Using double requestAnimationFrame ensures the modal is rendered and visible
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (!modalContainer) return;
      const focusable = modalContainer.querySelector(
        'input, button.modal-confirm, button.modal-cancel'
      ) as HTMLElement;
      if (focusable && document.body.contains(focusable)) {
        focusable.focus();
      }
    });
  });
}

/**
 * Hide the modal container.
 */
function hideModalContainer(): void {
  if (!modalContainer) return;
  modalContainer.classList.add('modal-hidden');
  modalContainer.classList.remove('modal-overlay-exit');
  const modal = modalContainer.querySelector('.modal');
  if (modal) {
    modal.classList.remove('modal-exit');
  }
}
