/**
 * Online/offline awareness: a persistent banner-style toast while offline
 * (the send outbox keeps typed messages safe; this tells the user why
 * nothing is arriving), cleared with a confirmation when back online.
 */
import { toast } from '../components/Toast';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';

const log = createLogger('connectivity');

let offlineNotificationId: string | null = null;

function handleOffline(): void {
  log.info('Connection lost');
  if (offlineNotificationId) return;
  offlineNotificationId = toast.warning(
    "You're offline. Messages you send will be kept and retried.",
    { duration: 0 }
  );
}

function handleOnline(): void {
  log.info('Connection restored');
  if (offlineNotificationId) {
    useStore.getState().dismissNotification(offlineNotificationId);
    offlineNotificationId = null;
    toast.success('Back online.');
  }
}

export function initConnectivity(): void {
  window.addEventListener('offline', handleOffline);
  window.addEventListener('online', handleOnline);
  if (!navigator.onLine) handleOffline();
}
