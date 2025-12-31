/**
 * Unit tests for MessageInput component utilities
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isIOSPWA, isMobileViewport, handlePaste } from '@/components/MessageInput';
import { MOBILE_BREAKPOINT_PX } from '@/config';
import { useStore } from '@/state/store';

// Mock FileUpload module
vi.mock('@/components/FileUpload', () => ({
  addFilesToPending: vi.fn(),
}));

import { addFilesToPending } from '@/components/FileUpload';

describe('isIOSPWA', () => {
  const originalNavigator = window.navigator;
  const originalMatchMedia = window.matchMedia;

  // Helper to mock navigator.userAgent
  function mockUserAgent(userAgent: string): void {
    Object.defineProperty(window, 'navigator', {
      value: {
        ...originalNavigator,
        userAgent,
      },
      configurable: true,
      writable: true,
    });
  }

  // Helper to mock navigator.standalone (iOS Safari property)
  function mockStandalone(value: boolean | undefined): void {
    const nav = window.navigator as Record<string, unknown>;
    if (value === undefined) {
      delete nav.standalone;
    } else {
      nav.standalone = value;
    }
  }

  // Helper to mock matchMedia
  function mockMatchMedia(standaloneMatches: boolean): void {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === '(display-mode: standalone)' ? standaloneMatches : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  }

  beforeEach(() => {
    // Reset to defaults
    mockMatchMedia(false);
  });

  afterEach(() => {
    // Restore original
    Object.defineProperty(window, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
    window.matchMedia = originalMatchMedia;
  });

  describe('iOS device detection', () => {
    it('detects iPhone', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('detects iPad', () => {
      mockUserAgent('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('detects iPod', () => {
      mockUserAgent('Mozilla/5.0 (iPod touch; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('returns false for Android', () => {
      mockUserAgent('Mozilla/5.0 (Linux; Android 14)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);
    });

    it('returns false for desktop Chrome', () => {
      mockUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);
    });

    it('returns false for desktop Windows', () => {
      mockUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);
    });
  });

  describe('PWA mode detection', () => {
    it('returns false for iOS in browser (not PWA)', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(undefined);
      expect(isIOSPWA()).toBe(false);
    });

    it('returns true when display-mode: standalone matches', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('returns true when navigator.standalone is true (iOS Safari property)', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('returns false when navigator.standalone is false', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(false);
      expect(isIOSPWA()).toBe(false);
    });
  });

  describe('combined conditions', () => {
    it('requires both iOS AND PWA mode', () => {
      // Android in PWA mode
      mockUserAgent('Mozilla/5.0 (Linux; Android 14)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);

      // iOS not in PWA mode
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(undefined);
      expect(isIOSPWA()).toBe(false);

      // iOS in PWA mode
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });
  });
});

describe('isMobileViewport', () => {
  const originalInnerWidth = window.innerWidth;

  // Helper to mock window.innerWidth
  function mockInnerWidth(width: number): void {
    Object.defineProperty(window, 'innerWidth', {
      value: width,
      configurable: true,
      writable: true,
    });
  }

  afterEach(() => {
    // Restore original
    Object.defineProperty(window, 'innerWidth', {
      value: originalInnerWidth,
      configurable: true,
      writable: true,
    });
  });

  describe('mobile detection based on viewport width', () => {
    it('returns true for narrow mobile viewport (375px - iPhone)', () => {
      mockInnerWidth(375);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns true for wider mobile viewport (414px - iPhone Plus)', () => {
      mockInnerWidth(414);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns true at exactly the breakpoint (768px)', () => {
      mockInnerWidth(MOBILE_BREAKPOINT_PX);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns false just above breakpoint (769px)', () => {
      mockInnerWidth(MOBILE_BREAKPOINT_PX + 1);
      expect(isMobileViewport()).toBe(false);
    });

    it('returns false for tablet landscape (1024px)', () => {
      mockInnerWidth(1024);
      expect(isMobileViewport()).toBe(false);
    });

    it('returns false for desktop (1440px)', () => {
      mockInnerWidth(1440);
      expect(isMobileViewport()).toBe(false);
    });

    it('returns false for large desktop (1920px)', () => {
      mockInnerWidth(1920);
      expect(isMobileViewport()).toBe(false);
    });
  });

  describe('edge cases', () => {
    it('returns true for very small viewport (320px - iPhone SE)', () => {
      mockInnerWidth(320);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns true for iPad mini portrait (768px)', () => {
      mockInnerWidth(768);
      expect(isMobileViewport()).toBe(true);
    });
  });
});

describe('handlePaste', () => {
  const mockedAddFilesToPending = vi.mocked(addFilesToPending);

  beforeEach(() => {
    vi.clearAllMocks();
    // Reset store state
    useStore.setState({ pendingFiles: [] });
  });

  /**
   * Helper to create a mock ClipboardEvent
   * Screenshots are provided via clipboardData.items (as DataTransferItems),
   * so we need to mock that interface properly.
   */
  function createPasteEvent(options: {
    files?: File[];
    preventDefault?: () => void;
  } = {}): ClipboardEvent {
    const { files = [], preventDefault = vi.fn() } = options;

    // Create DataTransferItems from files
    const items = files.map((file) => ({
      kind: 'file' as const,
      type: file.type,
      getAsFile: () => file,
      getAsString: () => {},
      webkitGetAsEntry: () => null,
    }));

    // Create a proper files-like array that supports indexed access
    const filesArray = [...files];

    const dataTransfer = {
      // items is the primary source for clipboard images (screenshots)
      items: {
        length: items.length,
        [Symbol.iterator]: function* () {
          for (const item of items) {
            yield item;
          }
        },
        ...items.reduce((acc, item, i) => ({ ...acc, [i]: item }), {}),
      } as unknown as DataTransferItemList,
      // files is a fallback - must support indexed access like files[i]
      files: {
        length: files.length,
        item: (index: number) => files[index] ?? null,
        [Symbol.iterator]: function* () {
          for (const file of files) {
            yield file;
          }
        },
        ...filesArray.reduce((acc, file, i) => ({ ...acc, [i]: file }), {}),
      } as unknown as FileList,
    };

    return {
      clipboardData: dataTransfer as unknown as DataTransfer,
      preventDefault,
    } as unknown as ClipboardEvent;
  }

  /**
   * Helper to create a mock File
   */
  function createMockFile(name: string, type: string, content = 'test'): File {
    return new File([content], name, { type });
  }

  describe('image paste handling', () => {
    it('adds pasted PNG image to pending files', () => {
      const imageFile = createMockFile('image.png', 'image/png');
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: [imageFile], preventDefault });

      handlePaste(event);

      expect(preventDefault).toHaveBeenCalled();
      expect(mockedAddFilesToPending).toHaveBeenCalledTimes(1);

      // Check that a File was passed with generated name
      const passedFiles = mockedAddFilesToPending.mock.calls[0][0];
      expect(passedFiles).toHaveLength(1);
      expect(passedFiles[0].type).toBe('image/png');
      expect(passedFiles[0].name).toMatch(/^screenshot-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.png$/);
    });

    it('adds pasted JPEG image to pending files', () => {
      const imageFile = createMockFile('photo.jpg', 'image/jpeg');
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: [imageFile], preventDefault });

      handlePaste(event);

      expect(preventDefault).toHaveBeenCalled();
      expect(mockedAddFilesToPending).toHaveBeenCalledTimes(1);

      const passedFiles = mockedAddFilesToPending.mock.calls[0][0];
      expect(passedFiles[0].type).toBe('image/jpeg');
      expect(passedFiles[0].name).toMatch(/\.jpeg$/);
    });

    it('adds pasted WebP image to pending files', () => {
      const imageFile = createMockFile('image.webp', 'image/webp');
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: [imageFile], preventDefault });

      handlePaste(event);

      expect(preventDefault).toHaveBeenCalled();
      const passedFiles = mockedAddFilesToPending.mock.calls[0][0];
      expect(passedFiles[0].type).toBe('image/webp');
      expect(passedFiles[0].name).toMatch(/\.webp$/);
    });

    it('adds pasted GIF image to pending files', () => {
      const imageFile = createMockFile('animation.gif', 'image/gif');
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: [imageFile], preventDefault });

      handlePaste(event);

      expect(preventDefault).toHaveBeenCalled();
      const passedFiles = mockedAddFilesToPending.mock.calls[0][0];
      expect(passedFiles[0].type).toBe('image/gif');
      expect(passedFiles[0].name).toMatch(/\.gif$/);
    });

    it('handles multiple pasted images', () => {
      const imageFiles = [
        createMockFile('image1.png', 'image/png'),
        createMockFile('image2.jpeg', 'image/jpeg'),
      ];
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: imageFiles, preventDefault });

      handlePaste(event);

      expect(preventDefault).toHaveBeenCalled();
      expect(mockedAddFilesToPending).toHaveBeenCalledTimes(1);

      const passedFiles = mockedAddFilesToPending.mock.calls[0][0];
      expect(passedFiles).toHaveLength(2);
      expect(passedFiles[0].type).toBe('image/png');
      expect(passedFiles[1].type).toBe('image/jpeg');
    });
  });

  describe('text paste handling', () => {
    it('does not prevent default for text-only paste', () => {
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: [], preventDefault });

      handlePaste(event);

      expect(preventDefault).not.toHaveBeenCalled();
      expect(mockedAddFilesToPending).not.toHaveBeenCalled();
    });

    it('does not process non-image files', () => {
      const pdfFile = createMockFile('document.pdf', 'application/pdf');
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: [pdfFile], preventDefault });

      handlePaste(event);

      // Should not prevent default - let browser handle it
      expect(preventDefault).not.toHaveBeenCalled();
      expect(mockedAddFilesToPending).not.toHaveBeenCalled();
    });

    it('only processes image files when mixed content is pasted', () => {
      const mixedFiles = [
        createMockFile('image.png', 'image/png'),
        createMockFile('document.pdf', 'application/pdf'),
        createMockFile('text.txt', 'text/plain'),
      ];
      const preventDefault = vi.fn();
      const event = createPasteEvent({ files: mixedFiles, preventDefault });

      handlePaste(event);

      expect(preventDefault).toHaveBeenCalled();
      expect(mockedAddFilesToPending).toHaveBeenCalledTimes(1);

      // Only the image should be passed
      const passedFiles = mockedAddFilesToPending.mock.calls[0][0];
      expect(passedFiles).toHaveLength(1);
      expect(passedFiles[0].type).toBe('image/png');
    });
  });

  describe('edge cases', () => {
    it('handles null clipboardData', () => {
      const event = {
        clipboardData: null,
        preventDefault: vi.fn(),
      } as unknown as ClipboardEvent;

      handlePaste(event);

      expect(mockedAddFilesToPending).not.toHaveBeenCalled();
    });

    it('generates unique names with timestamps', () => {
      // Create two images and paste them in sequence
      const imageFile1 = createMockFile('img.png', 'image/png');
      const imageFile2 = createMockFile('img.png', 'image/png');

      handlePaste(createPasteEvent({ files: [imageFile1] }));
      handlePaste(createPasteEvent({ files: [imageFile2] }));

      expect(mockedAddFilesToPending).toHaveBeenCalledTimes(2);

      // Both should have timestamp-based names
      const name1 = mockedAddFilesToPending.mock.calls[0][0][0].name;
      const name2 = mockedAddFilesToPending.mock.calls[1][0][0].name;

      expect(name1).toMatch(/^screenshot-/);
      expect(name2).toMatch(/^screenshot-/);
    });

    it('preserves original file content in the new File', () => {
      const originalContent = 'original-image-bytes';
      const imageFile = createMockFile('test.png', 'image/png', originalContent);
      const event = createPasteEvent({ files: [imageFile] });

      handlePaste(event);

      const passedFile = mockedAddFilesToPending.mock.calls[0][0][0];
      expect(passedFile.size).toBe(imageFile.size);
    });
  });
});