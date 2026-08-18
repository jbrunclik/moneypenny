/**
 * Focus trap utility for popups and modal dialogs.
 *
 * Keeps Tab/Shift+Tab cycling inside an open dialog so keyboard focus
 * cannot escape to the page underneath. Call trapTabKey from a keydown
 * handler while the dialog is open.
 */

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * Return visible, tabbable elements inside a container, in DOM order.
 * Elements hidden via display:none (offsetParent === null) are skipped.
 */
export function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.offsetParent !== null && el.getAttribute('tabindex') !== '-1'
  );
}

/**
 * Keep Tab navigation cycling inside the container.
 * No-op for non-Tab keys; safe to call from any keydown handler.
 */
export function trapTabKey(container: HTMLElement, e: KeyboardEvent): void {
  if (e.key !== 'Tab') return;

  const focusable = getFocusableElements(container);
  if (focusable.length === 0) {
    e.preventDefault();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement as HTMLElement | null;
  const inside = active !== null && container.contains(active);

  if (e.shiftKey) {
    if (!inside || active === first) {
      e.preventDefault();
      last.focus();
    }
  } else if (!inside || active === last) {
    e.preventDefault();
    first.focus();
  }
}
