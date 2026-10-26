/**
 * Signals about the app itself rather than a conversation: the background
 * attention badge, the offline banner, the new-version banner and the push
 * service worker and the controls the settings turn push on and off with.
 */
import { initVersionBanner } from '../../components/VersionBanner';
import { setPushControls } from '../../components/settings/notifications';
import { initAttention } from '../attention';
import { initConnectivity } from '../connectivity';
import { disablePush, enablePush, getPushState, registerServiceWorker, sendTestNotification } from '../push';

/**
 * Wire up the app status signals.
 */
export function initAppStatus(): void {
  initAttention();
  initConnectivity();
  initVersionBanner();
  // The settings' Notifications section turns push on and off through these
  setPushControls({ getState: getPushState, enable: enablePush, disable: disablePush, sendTest: sendTestNotification });
  // Keep an existing push subscription working after reloads; actual
  // permission requests only happen from the Settings toggle
  void registerServiceWorker();
}
