/**
 * Per-device artifact frame heights, so a frame reserves its space before it
 * reports its height (no scroll jolt on reload). Never stored server-side: the
 * same artifact is taller on a phone than on a laptop, so the key includes a
 * frame-width bucket.
 */
import { ARTIFACT_HEIGHT_CACHE_MAX_ENTRIES, ARTIFACT_HEIGHT_WIDTH_BUCKET_PX } from '../../config';
import type { ArtifactRef } from '../../types/api';

const STORAGE_KEY = 'artifact-heights';

type HeightCache = Record<string, number>;

export function heightCacheKey(ref: ArtifactRef, widthPx: number): string {
  return `${ref.id}@${ref.version}:${Math.round(widthPx / ARTIFACT_HEIGHT_WIDTH_BUCKET_PX)}`;
}

function read(): HeightCache {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as HeightCache;
  } catch {
    return {};
  }
}

export function getCachedHeight(key: string): number | null {
  const height = read()[key];
  return typeof height === 'number' ? height : null;
}

export function setCachedHeight(key: string, heightPx: number): void {
  const cache = read();
  delete cache[key]; // re-insert: newest last
  cache[key] = heightPx;
  const keys = Object.keys(cache);
  for (const old of keys.slice(0, Math.max(0, keys.length - ARTIFACT_HEIGHT_CACHE_MAX_ENTRIES))) {
    delete cache[old];
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Private mode / quota: the frame just starts at the placeholder height
  }
}
