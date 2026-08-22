/**
 * Device location capture for location-aware chat.
 *
 * Opt-in per device (localStorage): the browser permission prompt fires
 * only when the user enables the settings toggle. Fixes are cached and
 * refreshed at message-send time when older than LOCATION_MAX_AGE_MS.
 * Raw coordinates are sent per-request and never persisted server-side.
 */
import {
  LOCATION_ENABLE_RETRY_DELAYS_MS,
  LOCATION_ENABLE_TIMEOUT_MS,
  LOCATION_FIX_TIMEOUT_MS,
  LOCATION_MAX_AGE_MS,
} from '../config';
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

export type LocationFixFailure = 'unsupported' | 'denied' | 'unavailable' | 'timeout';

export type LocationFixResult =
  | { ok: true; fix: ClientLocation }
  | { ok: false; reason: LocationFixFailure };

function attemptFix(): Promise<LocationFixResult> {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        cachedFix = {
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy ?? null,
          timestamp_ms: pos.timestamp,
        };
        resolve({ ok: true, fix: cachedFix });
      },
      (err) => {
        log.debug('Geolocation failed on enable', { code: err.code, message: err.message });
        const reason: LocationFixFailure =
          err.code === 1 ? 'denied' : err.code === 3 ? 'timeout' : 'unavailable';
        resolve({ ok: false, reason });
      },
      { timeout: LOCATION_ENABLE_TIMEOUT_MS, maximumAge: LOCATION_MAX_AGE_MS }
    );
  });
}

/**
 * Request a fix for the settings enable flow, reporting WHY it failed so
 * the user can act on it (site permission vs. no positioning vs. slow fix).
 * Uses a generous timeout - the first fix includes the permission prompt
 * and a cold positioning lookup, unlike the send-time fast path.
 *
 * POSITION_UNAVAILABLE is retried with spaced attempts: on macOS,
 * CoreLocation routinely reports kCLErrorLocationUnknown on a cold start
 * and succeeds seconds later. Denial and timeout are final - denial won't
 * change and timeout already waited its full window.
 */
export async function requestLocationFix(): Promise<LocationFixResult> {
  if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
    return { ok: false, reason: 'unsupported' };
  }
  let result = await attemptFix();
  for (const delayMs of LOCATION_ENABLE_RETRY_DELAYS_MS) {
    if (result.ok || result.reason !== 'unavailable') break;
    await new Promise((r) => setTimeout(r, delayMs));
    result = await attemptFix();
  }
  return result;
}

/** Test-only: clear the module-level fix cache. */
export function __resetLocationCacheForTests(): void {
  cachedFix = null;
}
