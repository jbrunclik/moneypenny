/**
 * Client-side image compression: downscale and re-encode photos at attach
 * time so full-resolution camera images (4-8MB+) don't travel to the server,
 * the DB blob store, and the LLM when ~2048px is plenty.
 *
 * Fail-open by design: any decode/encode problem returns the original file.
 */
import {
  IMAGE_COMPRESSION_JPEG_QUALITY,
  IMAGE_COMPRESSION_MAX_EDGE_PX,
  IMAGE_COMPRESSION_MIN_BYTES,
  IMAGE_COMPRESSION_MIN_SAVINGS_RATIO,
} from '../config';
import { createLogger } from './logger';

const log = createLogger('image-compression');

/** Target dimensions when the long edge exceeds maxEdge; null = no resize. */
export function computeTargetSize(
  width: number,
  height: number,
  maxEdge: number
): { width: number; height: number } | null {
  const longEdge = Math.max(width, height);
  if (longEdge <= maxEdge) return null;
  const scale = maxEdge / longEdge;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

/** Only replace the original when the re-encode saves meaningful space. */
export function shouldUseCompressed(originalBytes: number, compressedBytes: number): boolean {
  return compressedBytes <= originalBytes * (1 - IMAGE_COMPRESSION_MIN_SAVINGS_RATIO);
}

/** Photographic formats worth re-encoding; GIF (animation) and SVG are not. */
export function isCompressibleImage(type: string): boolean {
  if (!type.startsWith('image/')) return false;
  return type !== 'image/gif' && type !== 'image/svg+xml';
}

/** Rename to match a JPEG re-encode (server infers nothing from names, but
 * a .png named file with image/jpeg content confuses humans). */
export function renameForJpeg(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? `${name.slice(0, dot)}.jpg` : `${name}.jpg`;
}

/** Sample the alpha channel; opaque images can drop PNG for JPEG. */
function hasTransparency(ctx: CanvasRenderingContext2D, width: number, height: number): boolean {
  const { data } = ctx.getImageData(0, 0, width, height);
  // Sample with a prime stride - full scans of 2048px images are wasteful
  for (let i = 3; i < data.length; i += 4 * 997) {
    if (data[i] < 255) return true;
  }
  return false;
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality?: number
): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/**
 * Downscale to IMAGE_COMPRESSION_MAX_EDGE_PX and re-encode (JPEG for opaque
 * images, PNG when transparency must survive). Returns the original file
 * when compression is unavailable, fails, or doesn't pay for itself.
 */
export async function compressImageFile(file: File): Promise<File> {
  if (!isCompressibleImage(file.type)) return file;
  if (file.size < IMAGE_COMPRESSION_MIN_BYTES) return file;
  if (typeof createImageBitmap === 'undefined') return file;

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch (error) {
    // Undecodable in this browser (e.g. HEIC outside Safari) - send as-is
    log.debug('Image decode failed, sending original', { error, fileName: file.name });
    return file;
  }

  try {
    const target = computeTargetSize(bitmap.width, bitmap.height, IMAGE_COMPRESSION_MAX_EDGE_PX);
    const width = target?.width ?? bitmap.width;
    const height = target?.height ?? bitmap.height;

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, width, height);

    const keepAlpha = file.type === 'image/png' && hasTransparency(ctx, width, height);
    const blob = keepAlpha
      ? await canvasToBlob(canvas, 'image/png')
      : await canvasToBlob(canvas, 'image/jpeg', IMAGE_COMPRESSION_JPEG_QUALITY);

    if (!blob || !shouldUseCompressed(file.size, blob.size)) return file;

    const name = blob.type === 'image/jpeg' ? renameForJpeg(file.name) : file.name;
    log.info('Compressed image', {
      fileName: file.name,
      from: file.size,
      to: blob.size,
      width,
      height,
      type: blob.type,
    });
    return new File([blob], name, { type: blob.type });
  } catch (error) {
    log.warn('Image compression failed, sending original', { error, fileName: file.name });
    return file;
  } finally {
    bitmap.close();
  }
}
