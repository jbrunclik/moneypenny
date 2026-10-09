/**
 * Swipe-down-to-dismiss for mobile bottom sheets (info popups, confirms, the
 * action sheet, the claims list). The drag starts only in the sheet's top
 * grab zone (handle + header) so the sheet's own scrollable body keeps
 * scrolling; it moves the sheet with transform only.
 */
import {
  MOBILE_BREAKPOINT_PX,
  SHEET_DISMISS_DISTANCE_RATIO,
  SHEET_DISMISS_MIN_PX,
  SHEET_DISMISS_VELOCITY_PX_PER_MS,
  SHEET_DRAG_UPWARD_RESISTANCE,
  SHEET_GRAB_ZONE_PX,
  SHEET_SETTLE_MS,
  SHEET_VELOCITY_WINDOW_MS,
} from '../config';

/** Sheet translation for a finger travel of `dy` (positive = down). */
export function sheetDragOffset(dy: number): number {
  return dy >= 0 ? dy : dy * SHEET_DRAG_UPWARD_RESISTANCE;
}

/** Whether a release after `dy` px at `velocity` px/ms dismisses the sheet. */
export function shouldDismissSheet(dy: number, velocity: number, sheetHeight: number): boolean {
  if (dy < SHEET_DISMISS_MIN_PX) return false;
  return dy > sheetHeight * SHEET_DISMISS_DISTANCE_RATIO || velocity >= SHEET_DISMISS_VELOCITY_PX_PER_MS;
}

function isInteractive(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest('button, a, input, textarea, select, [contenteditable="true"]');
}

/**
 * Let the user drag `sheet` down to dismiss it; `onDismiss` runs once the
 * sheet has slid out. Returns a cleanup function.
 */
export function attachSheetDismiss(sheet: HTMLElement, onDismiss: () => void): () => void {
  let startY = 0;
  let dy = 0;
  let samples: Array<{ t: number; y: number }> = [];
  let dragging = false;

  const settle = (transform: string, after?: () => void): void => {
    sheet.style.transition = `transform ${SHEET_SETTLE_MS}ms ease-out`;
    sheet.style.transform = transform;
    window.setTimeout(() => {
      sheet.style.transition = '';
      after?.();
    }, SHEET_SETTLE_MS);
  };

  const onStart = (e: TouchEvent): void => {
    if (window.innerWidth > MOBILE_BREAKPOINT_PX || e.touches.length !== 1) return;
    if (isInteractive(e.target)) return;
    const touch = e.touches[0];
    if (touch.clientY - sheet.getBoundingClientRect().top > SHEET_GRAB_ZONE_PX) return;
    dragging = true;
    startY = touch.clientY;
    dy = 0;
    samples = [{ t: e.timeStamp, y: touch.clientY }];
    sheet.style.transition = 'none';
  };

  const onMove = (e: TouchEvent): void => {
    if (!dragging) return;
    // The drag owns this gesture - no page/overlay rubber-band behind it
    e.preventDefault();
    const y = e.touches[0].clientY;
    dy = y - startY;
    samples.push({ t: e.timeStamp, y });
    samples = samples.filter((s) => e.timeStamp - s.t <= SHEET_VELOCITY_WINDOW_MS);
    sheet.style.transform = `translateY(${sheetDragOffset(dy)}px)`;
  };

  const onEnd = (e: TouchEvent): void => {
    if (!dragging) return;
    dragging = false;
    const first = samples[0];
    const elapsed = first ? e.timeStamp - first.t : 0;
    const velocity = first && elapsed > 0 ? (startY + dy - first.y) / elapsed : 0;
    if (shouldDismissSheet(dy, velocity, sheet.offsetHeight)) {
      settle(`translateY(${sheet.offsetHeight + SHEET_GRAB_ZONE_PX}px)`, () => {
        onDismiss();
        // Next open starts from the resting position
        sheet.style.transform = '';
      });
    } else {
      settle('');
    }
  };

  sheet.addEventListener('touchstart', onStart, { passive: true });
  sheet.addEventListener('touchmove', onMove, { passive: false });
  sheet.addEventListener('touchend', onEnd);
  sheet.addEventListener('touchcancel', onEnd);
  return () => {
    sheet.removeEventListener('touchstart', onStart);
    sheet.removeEventListener('touchmove', onMove);
    sheet.removeEventListener('touchend', onEnd);
    sheet.removeEventListener('touchcancel', onEnd);
  };
}
