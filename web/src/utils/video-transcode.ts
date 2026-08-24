/**
 * Client-side video transcoding before upload (WebCodecs via Mediabunny).
 *
 * Purpose: shrink large phone videos (HEVC/H.264 .mov, up to 100MB) into
 * ~720p H.264 MP4s so uploads survive slow connections. Runs entirely
 * in-browser with hardware codecs - no COOP/COEP headers, no WASM blob.
 *
 * FAIL-OPEN CONTRACT: every unsupported environment (no WebCodecs, HEVC
 * not decodable - e.g. Firefox, no H.264 encoder), error, timeout, or
 * non-shrinking result returns the ORIGINAL file. Transcoding is a
 * bandwidth optimization, never a gate.
 *
 * Mediabunny is dynamic-imported so Vite splits it into its own chunk,
 * fetched only when a transcode actually starts - it never weighs down
 * the main bundle.
 */

import {
  VIDEO_TRANSCODE_MIN_SIZE_BYTES,
  VIDEO_TRANSCODE_MAX_DIMENSION_PX,
  VIDEO_TRANSCODE_TIMEOUT_MS,
} from '../config';
import { createLogger } from './logger';

const log = createLogger('video-transcode');

function hasWebCodecs(): boolean {
  return typeof VideoEncoder !== 'undefined' && typeof VideoDecoder !== 'undefined';
}

/**
 * Transcode a large video file to H.264 MP4 for a smaller upload.
 * Returns the original file whenever transcoding is not possible or
 * not beneficial. onProgress receives a 0..1 fraction.
 */
export async function transcodeVideoFile(
  file: File,
  onProgress?: (fraction: number) => void
): Promise<File> {
  if (!file.type.startsWith('video/')) return file;
  if (file.size < VIDEO_TRANSCODE_MIN_SIZE_BYTES) return file;
  if (!hasWebCodecs()) {
    log.debug('WebCodecs unavailable, uploading original', { fileName: file.name });
    return file;
  }

  try {
    const {
      Input,
      Output,
      Conversion,
      BlobSource,
      BufferTarget,
      Mp4OutputFormat,
      ALL_FORMATS,
      QUALITY_MEDIUM,
      canEncodeVideo,
    } = await import('mediabunny');

    const dim = VIDEO_TRANSCODE_MAX_DIMENSION_PX;
    if (!(await canEncodeVideo('avc', { width: dim, height: dim }))) {
      log.info('H.264 encoding unsupported, uploading original', { fileName: file.name });
      return file;
    }

    const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });

    // A source we can't decode (e.g. HEVC on Firefox) would otherwise
    // silently produce a video-less output - check up front
    const videoTrack = await input.getPrimaryVideoTrack();
    if (!videoTrack || !(await videoTrack.canDecode())) {
      log.info('Source video not decodable in this browser, uploading original', {
        fileName: file.name,
        fileType: file.type,
      });
      return file;
    }

    const output = new Output({
      format: new Mp4OutputFormat(),
      target: new BufferTarget(),
    });

    const conversion = await Conversion.init({
      input,
      output,
      video: {
        width: dim,
        height: dim,
        fit: 'contain',
        codec: 'avc',
        bitrate: QUALITY_MEDIUM,
      },
      // Audio: no options - Mediabunny copies compatible tracks (AAC in
      // iPhone .mov) without re-encoding, so pre-Safari-26 devices that
      // lack WebCodecs audio still work
    });
    if (onProgress) {
      conversion.onProgress = onProgress;
    }

    // A hung conversion must not block the send forever
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      void conversion.cancel();
    }, VIDEO_TRANSCODE_TIMEOUT_MS);
    try {
      await conversion.execute();
    } finally {
      clearTimeout(timeout);
    }
    if (timedOut) {
      log.warn('Transcode timed out, uploading original', { fileName: file.name });
      return file;
    }

    const buffer = output.target.buffer;
    if (!buffer || buffer.byteLength === 0 || buffer.byteLength >= file.size) {
      log.info('Transcode did not shrink the file, uploading original', {
        fileName: file.name,
        originalSize: file.size,
        transcodedSize: buffer?.byteLength ?? 0,
      });
      return file;
    }

    const baseName = file.name.replace(/\.[^.]+$/, '');
    const result = new File([buffer], `${baseName}.mp4`, { type: 'video/mp4' });
    log.info('Video transcoded', {
      fileName: file.name,
      originalSize: file.size,
      transcodedSize: result.size,
      ratio: Math.round((result.size / file.size) * 100) / 100,
    });
    return result;
  } catch (error) {
    log.warn('Video transcode failed, uploading original', { error, fileName: file.name });
    return file;
  }
}
