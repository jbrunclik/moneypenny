/**
 * Touch tracking and the pan guard for the keyboard pinning
 * (core/keyboard-viewport.ts): whether a finger is down, and blocking the
 * touchmoves nothing can consume while the keyboard inset is active.
 */

export function isEditableElement(el: Element | null): boolean {
  if (!el) return false;
  return (
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'INPUT' ||
    (el as HTMLElement).isContentEditable
  );
}

/** True when some ancestor of the touch target can actually scroll. */
function touchCanScrollSomewhere(target: EventTarget | null): boolean {
  let el = target instanceof Element ? target : null;
  while (el && el !== document.documentElement) {
    if (el.scrollHeight > el.clientHeight) {
      const overflowY = getComputedStyle(el).overflowY;
      if (overflowY === 'auto' || overflowY === 'scroll') return true;
    }
    el = el.parentElement;
  }
  return false;
}

// With the keyboard open, iOS pans the VISUAL viewport within the still-
// full-height layout viewport - our shrunk page leaves a keyboard-sized
// pan range, so drags on non-scrollable screens (welcome screen) bounce
// the whole page. Prevent touchmoves nothing can consume while the inset
// is active. passive:false is required to be allowed to preventDefault.
const panGuard = (e: TouchEvent | Event): void => {
  if (!e.cancelable) return;
  // Escape hatch: if the viewport is ALREADY panned (a pan can slip in
  // via exempted targets, e.g. drags starting on the textarea), never
  // block - otherwise the recovery drag on empty space is prevented and
  // the page is stranded in the panned state
  if ((window.visualViewport?.offsetTop ?? 0) > 0) return;
  // Never interfere with drags inside form controls (text selection,
  // native textarea scrolling)
  if (e.target instanceof Element && isEditableElement(e.target.closest('textarea, input'))) {
    return;
  }
  if (touchCanScrollSomewhere(e.target)) return;
  e.preventDefault();
};

// UI-local (F2): listeners install once
let panGuardInstalled = false;

// Whether a finger is currently down - the stale-pan auto-reset must never
// yank the page mid-gesture (same reason as the recovery-drag escape hatch)
// UI-local (F2): touch tracking for the keyboard inset
let touchActive = false;
let touchTrackingInstalled = false;

export function installTouchTracking(): void {
  if (touchTrackingInstalled) return;
  touchTrackingInstalled = true;
  document.addEventListener('touchstart', () => {
    touchActive = true;
  }, { passive: true });
  const onTouchEnd = (e: Event): void => {
    touchActive = ((e as TouchEvent).touches?.length ?? 0) > 0;
  };
  document.addEventListener('touchend', onTouchEnd, { passive: true });
  document.addEventListener('touchcancel', onTouchEnd, { passive: true });
}

/** Whether a finger is down right now (read-only, for the layout checks). */
export function isTouchActive(): boolean {
  return touchActive;
}

export function setPanGuard(active: boolean): void {
  if (active === panGuardInstalled) return;
  panGuardInstalled = active;
  if (active) {
    document.addEventListener('touchmove', panGuard, { passive: false });
  } else {
    document.removeEventListener('touchmove', panGuard);
  }
}
