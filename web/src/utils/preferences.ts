/**
 * Per-device UI preferences (localStorage-backed, like location sharing).
 */

const SIDEBAR_PREVIEWS_KEY = 'sidebar_previews_enabled';
const SWIPE_QUICK_ACTION_KEY = 'swipe_quick_action';
const TEXT_SIZE_KEY = 'text_size';

export type SwipeQuickAction = 'archive' | 'delete';

/** Which action sits next to ⋯ More on a swiped conversation row. */
export function getSwipeQuickAction(): SwipeQuickAction {
  return localStorage.getItem(SWIPE_QUICK_ACTION_KEY) === 'delete' ? 'delete' : 'archive';
}

export function setSwipeQuickAction(action: SwipeQuickAction): void {
  localStorage.setItem(SWIPE_QUICK_ACTION_KEY, action);
}

/** Sidebar message previews: enabled unless explicitly turned off. */
export function isSidebarPreviewsEnabled(): boolean {
  return localStorage.getItem(SIDEBAR_PREVIEWS_KEY) !== 'false';
}

export function setSidebarPreviewsEnabled(enabled: boolean): void {
  localStorage.setItem(SIDEBAR_PREVIEWS_KEY, String(enabled));
}

/**
 * Text size (Nov 17 2026): scales the root font size, and with it every rem.
 * No smaller step: iOS zooms the page into a focused input under 16px.
 */
export const TEXT_SIZES = ['default', 'large', 'larger'] as const;
export type TextSize = (typeof TEXT_SIZES)[number];

export function getTextSize(): TextSize {
  const saved = localStorage.getItem(TEXT_SIZE_KEY);
  return TEXT_SIZES.find((size) => size === saved) ?? 'default';
}

export function setTextSize(size: TextSize): void {
  localStorage.setItem(TEXT_SIZE_KEY, size);
  applyTextSize(size);
}

/** Put the size on <html> (base.css scales the root font size from it). */
export function applyTextSize(size: TextSize = getTextSize()): void {
  if (size === 'default') {
    delete document.documentElement.dataset.textSize;
  } else {
    document.documentElement.dataset.textSize = size;
  }
}
