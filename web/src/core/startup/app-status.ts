/**
 * Signals about the app itself rather than a conversation: the background
 * attention badge, the offline banner, the new-version banner and the push
 * service worker.
 */
import { initVersionBanner } from '../../components/VersionBanner';
import { initAttention } from '../attention';
import { initConnectivity } from '../connectivity';
import { registerServiceWorker } from '../push';

/**
 * Wire up the app status signals.
 */
export function initAppStatus(): void {
  initAttention();
  initConnectivity();
  initVersionBanner();
  // Keep an existing push subscription working after reloads; actual
  // permission requests only happen from the Settings toggle
  void registerServiceWorker();
}
