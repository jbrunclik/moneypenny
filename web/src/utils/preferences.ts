/**
 * Per-device UI preferences (localStorage-backed, like location sharing).
 */

const SIDEBAR_PREVIEWS_KEY = 'sidebar_previews_enabled';

/** Sidebar message previews: enabled unless explicitly turned off. */
export function isSidebarPreviewsEnabled(): boolean {
  return localStorage.getItem(SIDEBAR_PREVIEWS_KEY) !== 'false';
}

export function setSidebarPreviewsEnabled(enabled: boolean): void {
  localStorage.setItem(SIDEBAR_PREVIEWS_KEY, String(enabled));
}
