/**
 * Per-device UI preferences (localStorage-backed, like location sharing).
 */

const SIDEBAR_PREVIEWS_KEY = 'sidebar_previews_enabled';
const SWIPE_QUICK_ACTION_KEY = 'swipe_quick_action';

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
