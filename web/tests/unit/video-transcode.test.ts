/**
 * Unit tests for client-side video transcoding (Mediabunny/WebCodecs).
 *
 * The contract is FAIL-OPEN: any unsupported environment, codec gap, or
 * error must return the ORIGINAL file so uploads never break. Transcoding
 * is a bandwidth optimization, not a requirement.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock mediabunny before importing the module under test - the module
// dynamic-imports it, and these tests control what the mock reports
const canEncodeVideo = vi.fn();
const executeMock = vi.fn();
const cancelMock = vi.fn();
let mockOutputBytes: Uint8Array = new Uint8Array(0);
let mockCanDecode = true;

vi.mock('mediabunny', () => ({
  Input: class {
    getPrimaryVideoTrack() {
      return { canDecode: () => Promise.resolve(mockCanDecode) };
    }
  },
  Output: class {
    target = {
      get buffer() {
        return mockOutputBytes.buffer;
      },
    };
  },
  BlobSource: class {},
  BufferTarget: class {},
  Mp4OutputFormat: class {},
  ALL_FORMATS: [],
  QUALITY_MEDIUM: 'quality-medium',
  canEncodeVideo,
  Conversion: {
    init: vi.fn().mockImplementation(() =>
      Promise.resolve({
        onProgress: null,
        execute: executeMock,
        cancel: cancelMock,
      })
    ),
  },
}));

import { transcodeVideoFile } from '@/utils/video-transcode';
import { VIDEO_TRANSCODE_MIN_SIZE_BYTES } from '@/config';

function makeVideoFile(sizeBytes: number, type = 'video/quicktime', name = 'clip.mov'): File {
  return new File([new Uint8Array(sizeBytes)], name, { type });
}

describe('transcodeVideoFile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCanDecode = true;
    // Simulate WebCodecs presence (jsdom has none)
    vi.stubGlobal('VideoEncoder', class {});
    vi.stubGlobal('VideoDecoder', class {});
    canEncodeVideo.mockResolvedValue(true);
    // Default: a much smaller output than any input we create
    mockOutputBytes = new Uint8Array(1024);
    executeMock.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns the original for non-video files', async () => {
    const file = new File([new Uint8Array(50 * 1024 * 1024)], 'doc.pdf', {
      type: 'application/pdf',
    });
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('skips small videos (not worth the battery)', async () => {
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES - 1);
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('returns the original when WebCodecs is unavailable', async () => {
    vi.unstubAllGlobals(); // jsdom: no VideoEncoder
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1);
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('returns the original when H.264 encoding is unsupported', async () => {
    canEncodeVideo.mockResolvedValue(false);
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1);
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('returns the original when the source cannot be decoded (e.g. HEVC on Firefox)', async () => {
    mockCanDecode = false;
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1);
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('returns the original when conversion throws', async () => {
    executeMock.mockRejectedValue(new Error('boom'));
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1);
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('returns the original when the transcode does not shrink the file', async () => {
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1);
    mockOutputBytes = new Uint8Array(file.size); // same size - no win
    expect(await transcodeVideoFile(file)).toBe(file);
  });

  it('returns a smaller MP4 on success, renamed to .mp4', async () => {
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1, 'video/quicktime', 'IMG_0042.mov');

    const result = await transcodeVideoFile(file);

    expect(result).not.toBe(file);
    expect(result.type).toBe('video/mp4');
    expect(result.name).toBe('IMG_0042.mp4');
    expect(result.size).toBeLessThan(file.size);
  });

  it('reports progress via the callback', async () => {
    const file = makeVideoFile(VIDEO_TRANSCODE_MIN_SIZE_BYTES + 1);
    const { Conversion } = await import('mediabunny');
    const progress = vi.fn();

    // Drive onProgress from execute() like the real library does
    executeMock.mockImplementation(async function (this: void) {
      const conv = await (Conversion.init as ReturnType<typeof vi.fn>).mock.results[0].value;
      conv.onProgress?.(0.5);
    });

    await transcodeVideoFile(file, progress);

    expect(progress).toHaveBeenCalledWith(0.5);
  });
});
