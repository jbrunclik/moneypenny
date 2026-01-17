/**
 * Toast notification component for displaying transient messages.
 *
 * Usage:
 *   import { showToast, initToast } from './components/Toast';
 *
 *   // Initialize once on app startup
 *   initToast();
 *
 *   // Show notifications
 *   showToast({ type: 'success', message: 'Saved!' });
 *   showToast({ type: 'error', message: 'Failed to save.' });
 *   showToast({
 *     type: 'error',
 *     message: 'Connection lost.',
 *     action: { label: 'Retry', onClick: () => reconnect() }
 *   });
 */

import { useStore, Notification } from '../state/store';
import { escapeHtml } from '../utils/dom';
import { CLOSE_ICON, CHECK_ICON, WARNING_ICON, INFO_ICON } from '../utils/icons';

// Re-export types for convenience
export type { Notification } from '../state/store';

// Default duration in milliseconds (0 = persistent)
const DEFAULT_DURATION = 5000;

// Icons for each notification type
const TYPE_ICONS: Record<string, string> = {
  success: CHECK_ICON,
  error: CLOSE_ICON,
  warning: WARNING_ICON,
  info: INFO_ICON,
};

// Toast container element
let toastContainer: HTMLDivElement | null = null;

// Track active toast timeouts for cleanup
const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

/**
 * Initialize the toast notification system.
 * Call this once during app initialization.
 */
export function initToast(): void {
  // Create container if it doesn't exist
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'toast-container';
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
  }

  // Subscribe to store changes
  useStore.subscribe(
    (state) => state.notifications,
    (notifications) => {
      renderToasts(notifications);
    }
  );

  // Handle click events via delegation
  toastContainer.addEventListener('click', handleToastClick);

  // Clean up timeouts on page unload to prevent memory leaks
  window.addEventListener('beforeunload', cleanupToastTimeouts);
}

/**
 * Clean up all toast timeouts (called on page unload).
 */
function cleanupToastTimeouts(): void {
  toastTimeouts.forEach((timeout) => clearTimeout(timeout));
  toastTimeouts.clear();
}

/**
 * Show a toast notification.
 */
export function showToast(options: {
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  action?: { label: string; onClick: () => void };
  duration?: number;
}): string {
  const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  const duration = options.duration ?? (options.action ? 0 : DEFAULT_DURATION);

  useStore.getState().addNotification({
    id,
    type: options.type,
    message: options.message,
    action: options.action,
    duration,
  });

  // Auto-dismiss after duration (if not persistent)
  if (duration > 0) {
    const timeout = setTimeout(() => {
      dismissToast(id);
    }, duration);
    toastTimeouts.set(id, timeout);
  }

  return id;
}

/**
 * Dismiss a toast notification.
 */
export function dismissToast(id: string): void {
  // Clear any pending timeout
  const timeout = toastTimeouts.get(id);
  if (timeout) {
    clearTimeout(timeout);
    toastTimeouts.delete(id);
  }

  // Start exit animation
  const toastEl = document.querySelector(`[data-toast-id="${id}"]`);
  if (toastEl) {
    toastEl.classList.add('toast-exit');
    // Remove from store after animation completes
    setTimeout(() => {
      useStore.getState().dismissNotification(id);
    }, 200); // Match CSS animation duration
  } else {
    // No element found, just remove from store
    useStore.getState().dismissNotification(id);
  }
}

/**
 * Dismiss all toast notifications.
 */
export function dismissAllToasts(): void {
  const notifications = useStore.getState().notifications;
  notifications.forEach((n) => dismissToast(n.id));
}

/**
 * Handle click events on toasts.
 */
function handleToastClick(e: MouseEvent): void {
  const target = e.target as HTMLElement;

  // Handle dismiss button click
  const dismissBtn = target.closest('.toast-dismiss');
  if (dismissBtn) {
    const toastEl = dismissBtn.closest('[data-toast-id]');
    const id = toastEl?.getAttribute('data-toast-id');
    if (id) {
      dismissToast(id);
    }
    return;
  }

  // Handle action button click
  const actionBtn = target.closest('.toast-action');
  if (actionBtn) {
    const toastEl = actionBtn.closest('[data-toast-id]');
    const id = toastEl?.getAttribute('data-toast-id');
    if (id) {
      const notification = useStore
        .getState()
        .notifications.find((n) => n.id === id);
      if (notification?.action?.onClick) {
        notification.action.onClick();
        dismissToast(id);
      }
    }
    return;
  }
}

/**
 * Render all toasts to the container.
 */
function renderToasts(notifications: Notification[]): void {
  if (!toastContainer) return;

  // Build HTML for all toasts
  const html = notifications
    .map((n) => {
      const icon = TYPE_ICONS[n.type] || INFO_ICON;
      const actionHtml = n.action
        ? `<button class="toast-action">${escapeHtml(n.action.label)}</button>`
        : '';

      return `
        <div class="toast toast-${n.type}" data-toast-id="${n.id}" role="alert">
          <span class="toast-icon">${icon}</span>
          <span class="toast-message">${escapeHtml(n.message)}</span>
          ${actionHtml}
          <button class="toast-dismiss" aria-label="Dismiss">${CLOSE_ICON}</button>
        </div>
      `;
    })
    .join('');

  toastContainer.innerHTML = html;
}

// Convenience functions for common toast types
export const toast = {
  success: (message: string, options?: { duration?: number }) =>
    showToast({ type: 'success', message, ...options }),

  error: (
    message: string,
    options?: { action?: { label: string; onClick: () => void }; duration?: number }
  ) => showToast({ type: 'error', message, ...options }),

  warning: (message: string, options?: { duration?: number }) =>
    showToast({ type: 'warning', message, ...options }),

  info: (message: string, options?: { duration?: number }) =>
    showToast({ type: 'info', message, ...options }),

  /**
   * Show a persistent loading toast.
   * Returns an object with dismiss() to manually dismiss the toast.
   */
  loading: (message: string) => {
    const id = showToast({ type: 'info', message, duration: 0 });
    return {
      dismiss: () => dismissToast(id),
    };
  },
};
