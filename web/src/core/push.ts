/**
 * Web Push client: service worker registration and subscription
 * lifecycle.
 *
 * enablePush() MUST be called from a user gesture (settings toggle) -
 * iOS hard requirement, Chrome best practice. The service worker itself
 * is registered eagerly on app init so an existing subscription keeps
 * working after reloads.
 *
 * iOS: push only works when the app is installed to the Home Screen
 * (iOS 16.4+); see isIosWithoutStandalone() for the settings hint.
 */

import { push as pushApi } from '../api/client';
import { createLogger } from '../utils/logger';

const log = createLogger('push');

export type PushState =
  | 'unsupported'
  | 'ios-needs-install'
  | 'server-disabled'
  | 'denied'
  | 'subscribed'
  | 'not-subscribed';

function isSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

function isIosWithoutStandalone(): boolean {
  const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone === true
    || window.matchMedia('(display-mode: standalone)').matches;
  return isIos && !standalone;
}

/**
 * Decode a base64url VAPID public key into the Uint8Array form
 * PushManager.subscribe expects.
 */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

/**
 * Register the service worker. Safe to call on every app init; the
 * browser deduplicates registrations.
 */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!isSupported()) return null;
  try {
    const registration = await navigator.serviceWorker.register('/sw.js');
    log.debug('Service worker registered', { scope: registration.scope });
    setupWorkerMessageListener();
    return registration;
  } catch (error) {
    log.warn('Service worker registration failed', { error });
    return null;
  }
}

let workerMessageListenerInstalled = false;

/**
 * Handle notification taps relayed by the service worker. The SW can't
 * hard-navigate: an identical-hash navigation is a no-op (an
 * already-open conversation would never refresh) and a reload would
 * drop app state. Instead the app routes via the hash and pulls new
 * messages through the sync manager.
 */
function setupWorkerMessageListener(): void {
  if (workerMessageListenerInstalled) return;
  workerMessageListenerInstalled = true;

  navigator.serviceWorker.addEventListener('message', (event: MessageEvent) => {
    const data = event.data as { type?: string; url?: string } | null;
    if (data?.type !== 'push-navigate' || !data.url) return;

    const hashIndex = data.url.indexOf('#');
    const targetHash = hashIndex >= 0 ? data.url.slice(hashIndex) : '';
    log.info('Notification tap navigation', { url: data.url });

    if (targetHash && window.location.hash !== targetHash) {
      // Different route: the hashchange router loads fresh data
      window.location.hash = targetHash;
    } else {
      // Already on the target conversation - fetch what the
      // notification was about
      void import('../sync/SyncManager').then(({ getSyncManager }) => {
        getSyncManager()?.incrementalSync();
      });
    }
  });
}

/**
 * Re-upload this device's current subscription if one exists.
 *
 * Called once per app load (after auth). The subscribe endpoint upserts
 * by endpoint, so this is an idempotent no-op in the steady state - its
 * job is healing silent endpoint rotation by the push service: the
 * rotated endpoint gets stored on the next app open and the dead row is
 * pruned on its next failed send. (A SW pushsubscriptionchange handler
 * can't do this - it has no access to the auth token.)
 */
export async function resyncPushSubscription(): Promise<void> {
  if (!isSupported()) return;
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) return;

    const json = subscription.toJSON();
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return;

    await pushApi.subscribe({
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
    });
    log.debug('Push subscription re-synced');
  } catch (error) {
    // Best-effort: the next app open retries
    log.warn('Push subscription re-sync failed', { error });
  }
}

/**
 * Current push state for the settings UI.
 */
export async function getPushState(): Promise<PushState> {
  if (!isSupported()) {
    return isIosWithoutStandalone() ? 'ios-needs-install' : 'unsupported';
  }
  try {
    const { enabled } = await pushApi.getVapidPublicKey();
    if (!enabled) return 'server-disabled';
  } catch {
    return 'server-disabled';
  }
  if (Notification.permission === 'denied') return 'denied';

  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  return subscription ? 'subscribed' : 'not-subscribed';
}

/**
 * Request permission, subscribe, and store the subscription.
 * Must run from a user gesture. Returns the new state.
 */
export async function enablePush(): Promise<PushState> {
  if (!isSupported()) {
    return isIosWithoutStandalone() ? 'ios-needs-install' : 'unsupported';
  }

  const { enabled, public_key: publicKey } = await pushApi.getVapidPublicKey();
  if (!enabled || !publicKey) return 'server-disabled';

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    log.info('Notification permission not granted', { permission });
    return permission === 'denied' ? 'denied' : 'not-subscribed';
  }

  const registration = (await navigator.serviceWorker.getRegistration())
    ?? (await registerServiceWorker());
  if (!registration) return 'unsupported';
  await navigator.serviceWorker.ready;

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey).buffer as ArrayBuffer,
  });

  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    log.warn('Subscription missing fields', { json });
    return 'not-subscribed';
  }

  await pushApi.subscribe({
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
  });
  log.info('Push enabled');
  return 'subscribed';
}

/**
 * Unsubscribe this device and remove the stored subscription.
 */
export async function disablePush(): Promise<PushState> {
  if (!isSupported()) return 'unsupported';

  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return 'not-subscribed';

  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  try {
    await pushApi.unsubscribe(endpoint);
  } catch (error) {
    // Server cleanup is best-effort; a dead subscription gets pruned on
    // the next send anyway
    log.warn('Failed to remove subscription server-side', { error });
  }
  log.info('Push disabled');
  return 'not-subscribed';
}

/**
 * Send a test notification to this user's devices.
 */
export async function sendTestNotification(): Promise<string> {
  const { status } = await pushApi.sendTest();
  return status;
}
