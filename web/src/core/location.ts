/**
 * Device location capture for location-aware chat.
 *
 * Opt-in per device (localStorage): the browser permission prompt fires
 * only when the user enables the settings toggle. Fixes are cached and
 * refreshed at message-send time when older than LOCATION_MAX_AGE_MS.
 * Raw coordinates are sent per-request and never persisted server-side.
 */
import { LOCATION_FIX_TIMEOUT_MS, LOCATION_MAX_AGE_MS } from '../config';
import type { ClientLocation } from '../types/api';
import { createLogger } from '../utils/logger';

const log = createLogger('location');
const STORAGE_KEY = 'location_sharing_enabled';

let cachedFix: ClientLocation | null = null;

export function isLocationSharingEnabled(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'true';
}

export function setLocationSharingEnabled(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, String(enabled));
  if (!enabled) cachedFix = null;
}

/** Get the device location, or null (disabled / denied / unavailable / timeout). */
export async function getClientLocation(): Promise<ClientLocation | null> {
  if (!isLocationSharingEnabled()) return null;
  if (typeof navigator === 'undefined' || !('geolocation' in navigator)) return null;
  if (cachedFix && Date.now() - cachedFix.timestamp_ms < LOCATION_MAX_AGE_MS) {
    return cachedFix;
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        cachedFix = {
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy ?? null,
          timestamp_ms: pos.timestamp,
        };
        resolve(cachedFix);
      },
      (err) => {
        log.debug('Geolocation unavailable', { code: err.code });
        resolve(null);
      },
      { timeout: LOCATION_FIX_TIMEOUT_MS, maximumAge: LOCATION_MAX_AGE_MS }
    );
  });
}

/** Test-only: clear the module-level fix cache. */
export function __resetLocationCacheForTests(): void {
  cachedFix = null;
}
