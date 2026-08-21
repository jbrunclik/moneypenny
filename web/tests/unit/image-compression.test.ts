/**
 * Unit tests for client-side image compression decisions.
 * Canvas/createImageBitmap paths are exercised in a real browser; here we
 * test the pure decision logic and the safe-fallback behavior.
 */
import { describe, it, expect } from 'vitest';
import {
  computeTargetSize,
  shouldUseCompressed,
  isCompressibleImage,
  renameForJpeg,
  compressImageFile,
} from '@/utils/image-compression';
import { IMAGE_COMPRESSION_MAX_EDGE_PX } from '@/config';

describe('computeTargetSize', () => {
  it('returns null when the image is within the max edge', () => {
    expect(computeTargetSize(800, 600, 2048)).toBeNull();
    expect(computeTargetSize(2048, 1000, 2048)).toBeNull();
  });

  it('scales the long edge down to the max, preserving aspect ratio', () => {
    expect(computeTargetSize(4096, 2048, 2048)).toEqual({ width: 2048, height: 1024 });
    expect(computeTargetSize(1000, 4000, 2048)).toEqual({ width: 512, height: 2048 });
  });

  it('rounds to whole pixels and never returns zero', () => {
    const target = computeTargetSize(4097, 3, 2048);
    expect(target).toEqual({ width: 2048, height: 1 });
  });
});

describe('shouldUseCompressed', () => {
  it('accepts the compressed version only when it saves meaningful space', () => {
    expect(shouldUseCompressed(1_000_000, 500_000)).toBe(true);
    expect(shouldUseCompressed(1_000_000, 950_000)).toBe(false);
    expect(shouldUseCompressed(1_000_000, 1_200_000)).toBe(false);
  });
});

describe('isCompressibleImage', () => {
  it('accepts photographic formats', () => {
    expect(isCompressibleImage('image/jpeg')).toBe(true);
    expect(isCompressibleImage('image/png')).toBe(true);
    expect(isCompressibleImage('image/webp')).toBe(true);
    expect(isCompressibleImage('image/heic')).toBe(true);
  });

  it('rejects animated/vector formats and non-images', () => {
    expect(isCompressibleImage('image/gif')).toBe(false);
    expect(isCompressibleImage('image/svg+xml')).toBe(false);
    expect(isCompressibleImage('video/mp4')).toBe(false);
    expect(isCompressibleImage('application/pdf')).toBe(false);
  });
});

describe('renameForJpeg', () => {
  it('swaps the extension for jpg', () => {
    expect(renameForJpeg('photo.png')).toBe('photo.jpg');
    expect(renameForJpeg('IMG_1234.HEIC')).toBe('IMG_1234.jpg');
  });

  it('appends jpg when there is no extension', () => {
    expect(renameForJpeg('photo')).toBe('photo.jpg');
  });

  it('only touches the final extension', () => {
    expect(renameForJpeg('my.holiday.photo.png')).toBe('my.holiday.photo.jpg');
  });
});

describe('compressImageFile fallback', () => {
  it('returns the original file when decoding is unavailable (jsdom)', async () => {
    const file = new File([new Uint8Array(600_000)], 'big.jpg', { type: 'image/jpeg' });
    const result = await compressImageFile(file);
    expect(result).toBe(file);
  });

  it('returns non-compressible files untouched', async () => {
    const file = new File([new Uint8Array(600_000)], 'anim.gif', { type: 'image/gif' });
    const result = await compressImageFile(file);
    expect(result).toBe(file);
  });

  it('skips files already below the size threshold', async () => {
    const file = new File([new Uint8Array(1000)], 'tiny.jpg', { type: 'image/jpeg' });
    const result = await compressImageFile(file);
    expect(result).toBe(file);
  });
});

describe('config sanity', () => {
  it('max edge is a sane resolution for LLM consumption', () => {
    expect(IMAGE_COMPRESSION_MAX_EDGE_PX).toBeGreaterThanOrEqual(1024);
  });
});
