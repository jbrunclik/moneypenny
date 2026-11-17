/**
 * Background-attention signals: when a turn finishes while the tab/app is
 * hidden, prefix the tab title with a counter ("(2) Moneypenny") and set
 * the PWA app badge (installed iOS/Android home-screen icon). Both clear
 * the moment the user returns - without this there is no ambient signal
 * that an answer is ready after switching tabs or apps.
 */
import { APP_NAME } from '../config';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';

const log = createLogger('attention');

// UI-local (F2): the hidden-tab title badge until the user returns
let baseTitle = '';
let pendingCount = 0;

function applyBadge(): void {
  document.title = pendingCount > 0 ? `(${pendingCount}) ${baseTitle}` : baseTitle;
  const nav = navigator as Navigator & {
    setAppBadge?: (count: number) => Promise<void>;
    clearAppBadge?: () => Promise<void>;
  };
  if (pendingCount > 0) {
    nav.setAppBadge?.(pendingCount)?.catch(() => undefined);
  } else {
    nav.clearAppBadge?.()?.catch(() => undefined);
  }
}

function clearAttention(): void {
  if (pendingCount > 0) {
    pendingCount = 0;
    applyBadge();
    return;
  }
  // A push may have set the app badge (sw.js) while the app was closed
  const nav = navigator as Navigator & { clearAppBadge?: () => Promise<void> };
  nav.clearAppBadge?.()?.catch(() => undefined);
}

/** Test hook: reset module state between tests. */
export function _resetAttention(): void {
  pendingCount = 0;
  baseTitle = '';
}

/**
 * The window title for a conversation: its title first (tabs, the window
 * switcher and history show which chat it is), then the app's name.
 */
export function titleFor(conversationTitle: string | null | undefined): string {
  const title = conversationTitle?.trim();
  return title ? `${title} · ${APP_NAME}` : APP_NAME;
}

function setBaseTitle(title: string): void {
  if (title === baseTitle) return;
  baseTitle = title;
  applyBadge();
}

export function initAttention(): void {
  baseTitle = document.title;
  // The open conversation names the window; other views show the app's name.
  // An anonymous chat stays unnamed: the title would land in the browser's
  // history and the system's window list
  const shownTitle = (state: ReturnType<typeof useStore.getState>): string | undefined => {
    const conv = state.currentConversation;
    return conv && !state.anonymousModeByConversation.get(conv.id) ? conv.title : undefined;
  };
  setBaseTitle(titleFor(shownTitle(useStore.getState())));
  useStore.subscribe(shownTitle, (title) => setBaseTitle(titleFor(title)));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) clearAttention();
  });
  window.addEventListener('focus', clearAttention);
}

/** A turn completed - signal it if the user isn't looking. */
export function notifyTurnFinished(): void {
  if (!document.hidden) return;
  pendingCount += 1;
  log.debug('Turn finished while hidden', { pendingCount });
  applyBadge();
}
