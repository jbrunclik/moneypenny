import { describe, it, expect } from 'vitest';
import { maxSizeForType, resolveFileType, shouldTranscodeVideo } from '../../src/components/FileUpload';
import type { UploadConfig } from '../../src/types/api';

const config: UploadConfig = {
  maxFileSize: 20 * 1024 * 1024,
  maxVideoFileSize: 100 * 1024 * 1024,
  maxFilesPerMessage: 10,
  allowedFileTypes: ['image/png', 'video/mp4'],
};

describe('maxSizeForType', () => {
  it('returns video limit for video MIME types', () => {
    expect(maxSizeForType(config, 'video/mp4')).toBe(100 * 1024 * 1024);
    expect(maxSizeForType(config, 'video/quicktime')).toBe(100 * 1024 * 1024);
  });

  it('returns default limit for non-video types', () => {
    expect(maxSizeForType(config, 'image/png')).toBe(20 * 1024 * 1024);
    expect(maxSizeForType(config, 'application/pdf')).toBe(20 * 1024 * 1024);
  });
});

describe('shouldTranscodeVideo', () => {
  it('transcodes videos when the server accepts the mp4 output', () => {
    expect(shouldTranscodeVideo('video/quicktime', ['video/quicktime', 'video/mp4'])).toBe(true);
    expect(shouldTranscodeVideo('video/mp4', ['video/mp4'])).toBe(true);
  });

  it('never transcodes when video/mp4 is not server-allowed', () => {
    // The transcoder outputs mp4 - producing it when the server rejects
    // it guarantees a failed send (observed in prod: quicktime-only list)
    expect(shouldTranscodeVideo('video/quicktime', ['video/quicktime'])).toBe(false);
  });

  it('ignores non-video files', () => {
    expect(shouldTranscodeVideo('image/png', ['video/mp4'])).toBe(false);
  });
});

describe('resolveFileType', () => {
  it('resolves HEIC by extension when the browser reports no type', () => {
    // Windows/Linux pickers and some Android browsers report HEIC as
    // empty or octet-stream - the extension is the only signal
    expect(resolveFileType(new File([], 'IMG_1234.heic', { type: '' }))).toBe('image/heic');
    expect(
      resolveFileType(new File([], 'IMG_1234.heif', { type: 'application/octet-stream' }))
    ).toBe('image/heif');
  });

  it('is case-insensitive on the extension', () => {
    expect(resolveFileType(new File([], 'IMG_1234.HEIC', { type: '' }))).toBe('image/heic');
  });

  it('trusts a concrete browser-declared type', () => {
    expect(resolveFileType(new File([], 'photo.heic', { type: 'image/heic' }))).toBe(
      'image/heic'
    );
    expect(resolveFileType(new File([], 'photo.png', { type: 'image/png' }))).toBe('image/png');
  });

  it('leaves unknown extensions unchanged', () => {
    expect(resolveFileType(new File([], 'data.bin', { type: '' }))).toBe('');
    expect(
      resolveFileType(new File([], 'data.xyz', { type: 'application/octet-stream' }))
    ).toBe('application/octet-stream');
  });
});
