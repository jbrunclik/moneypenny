import { describe, it, expect } from 'vitest';
import { maxSizeForType } from '../../src/components/FileUpload';
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
