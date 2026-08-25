/**
 * Background-attention signals: when a turn finishes while the tab/app is
 * hidden, prefix the tab title with a counter ("(2) Moneypenny") and set
 * the PWA app badge (installed iOS/Android home-screen icon). Both clear
 * the moment the user returns - without this there is no ambient signal
 * that an answer is ready after switching tabs or apps.
 */
import { createLogger } from '../utils/logger';

const log = createLogger('attention');

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
  if (pendingCount === 0) return;
  pendingCount = 0;
  applyBadge();
}

/** Test hook: reset module state between tests. */
export function _resetAttention(): void {
  pendingCount = 0;
  baseTitle = '';
}

export function initAttention(): void {
  baseTitle = document.title;
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
