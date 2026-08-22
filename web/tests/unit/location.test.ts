/**
 * Tests for device location capture (core/location.ts)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  __resetLocationCacheForTests,
  getClientLocation,
  isLocationSharingEnabled,
  requestLocationFix,
  setLocationSharingEnabled,
} from '../../src/core/location';

function mockGeolocation(
  impl: (success: PositionCallback, error?: PositionErrorCallback) => void
): ReturnType<typeof vi.fn> {
  const getCurrentPosition = vi.fn(impl);
  vi.stubGlobal('navigator', { geolocation: { getCurrentPosition } });
  return getCurrentPosition;
}

describe('location', () => {
  beforeEach(() => {
    localStorage.clear();
    __resetLocationCacheForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('is disabled by default', () => {
    expect(isLocationSharingEnabled()).toBe(false);
  });

  it('returns null when sharing is disabled', async () => {
    mockGeolocation((success) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: 1755300000000,
      } as GeolocationPosition)
    );
    expect(await getClientLocation()).toBeNull();
  });

  it('returns a fix when enabled and permission granted', async () => {
    setLocationSharingEnabled(true);
    mockGeolocation((success) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: 1755300000000,
      } as GeolocationPosition)
    );
    const fix = await getClientLocation();
    expect(fix).toEqual({
      lat: 50.08,
      lon: 14.42,
      accuracy_m: 15,
      timestamp_ms: 1755300000000,
    });
  });

  it('returns cached fix without re-querying when fresh', async () => {
    setLocationSharingEnabled(true);
    const getPos = mockGeolocation((success) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: Date.now(),
      } as GeolocationPosition)
    );
    await getClientLocation();
    await getClientLocation();
    expect(getPos).toHaveBeenCalledTimes(1);
  });

  it('resolves null on permission denial', async () => {
    setLocationSharingEnabled(true);
    mockGeolocation((_success, error) =>
      error?.({ code: 1, message: 'denied' } as GeolocationPositionError)
    );
    expect(await getClientLocation()).toBeNull();
  });

  it('resolves null when geolocation API is missing', async () => {
    setLocationSharingEnabled(true);
    vi.stubGlobal('navigator', {});
    expect(await getClientLocation()).toBeNull();
  });

  it('requestLocationFix reports success and caches the fix', async () => {
    setLocationSharingEnabled(true);
    const getPos = mockGeolocation((success) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: Date.now(),
      } as GeolocationPosition)
    );
    const result = await requestLocationFix();
    expect(result.ok).toBe(true);
    // The enable-time fix is cached: the next send reuses it
    await getClientLocation();
    expect(getPos).toHaveBeenCalledTimes(1);
  });

  it('requestLocationFix distinguishes denial, unavailability and timeout', async () => {
    setLocationSharingEnabled(true);
    for (const [code, reason] of [
      [1, 'denied'],
      [2, 'unavailable'],
      [3, 'timeout'],
    ] as const) {
      __resetLocationCacheForTests();
      mockGeolocation((_success, error) =>
        error?.({ code, message: '' } as GeolocationPositionError)
      );
      expect(await requestLocationFix()).toEqual({ ok: false, reason });
    }
  });

  it('requestLocationFix reports unsupported when the API is missing', async () => {
    setLocationSharingEnabled(true);
    vi.stubGlobal('navigator', {});
    expect(await requestLocationFix()).toEqual({ ok: false, reason: 'unsupported' });
  });

  it('clears the cached fix when sharing is disabled', async () => {
    setLocationSharingEnabled(true);
    const getPos = mockGeolocation((success) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: Date.now(),
      } as GeolocationPosition)
    );
    await getClientLocation();
    setLocationSharingEnabled(false);
    setLocationSharingEnabled(true);
    await getClientLocation();
    expect(getPos).toHaveBeenCalledTimes(2);
  });
});
