/**
 * Unit tests for MessageInput component utilities
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  isIOSPWA,
  isIOS,
  shouldAutoFocusInput,
  isMobileViewport,
  handlePaste,
  showUploadProgress,
  hideUploadProgress,
  updateUploadProgress,
} from '@/components/MessageInput';
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

describe('isIOS', () => {
  const originalNavigator = window.navigator;

  // Helper to mock navigator properties
  function mockNavigator(props: { userAgent?: string; platform?: string; maxTouchPoints?: number }): void {
    Object.defineProperty(window, 'navigator', {
      value: {
        ...originalNavigator,
        userAgent: props.userAgent ?? originalNavigator.userAgent,
        platform: props.platform ?? originalNavigator.platform,
        maxTouchPoints: props.maxTouchPoints ?? 0,
      },
      configurable: true,
      writable: true,
    });
  }

  afterEach(() => {
    Object.defineProperty(window, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
  });

  describe('legacy iOS detection', () => {
    it('returns true for iPhone user agent', () => {
      mockNavigator({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' });
      expect(isIOS()).toBe(true);
    });

    it('returns true for iPad user agent', () => {
      mockNavigator({ userAgent: 'Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)' });
      expect(isIOS()).toBe(true);
    });

    it('returns true for iPod user agent', () => {
      mockNavigator({ userAgent: 'Mozilla/5.0 (iPod; CPU iPhone OS 15_0 like Mac OS X)' });
      expect(isIOS()).toBe(true);
    });
  });

  describe('iPadOS 13+ detection (MacIntel with touch)', () => {
    it('returns true for MacIntel with touch points (iPadOS 13+)', () => {
      mockNavigator({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        platform: 'MacIntel',
        maxTouchPoints: 5,
      });
      expect(isIOS()).toBe(true);
    });

    it('returns false for real Mac (MacIntel without touch)', () => {
      mockNavigator({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        platform: 'MacIntel',
        maxTouchPoints: 0,
      });
      expect(isIOS()).toBe(false);
    });

    it('returns false for Mac with 1 touch point (trackpad)', () => {
      mockNavigator({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        platform: 'MacIntel',
        maxTouchPoints: 1,
      });
      expect(isIOS()).toBe(false);
    });
  });

  describe('non-iOS platforms', () => {
    it('returns false for Android', () => {
      mockNavigator({ userAgent: 'Mozilla/5.0 (Linux; Android 14)' });
      expect(isIOS()).toBe(false);
    });

    it('returns false for Windows', () => {
      mockNavigator({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        platform: 'Win32',
      });
      expect(isIOS()).toBe(false);
    });

    it('returns false for Linux', () => {
      mockNavigator({
        userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
        platform: 'Linux x86_64',
      });
      expect(isIOS()).toBe(false);
    });
  });
});

describe('shouldAutoFocusInput', () => {
  const originalNavigator = window.navigator;

  // Helper to mock navigator properties
  function mockNavigator(props: { userAgent?: string; platform?: string; maxTouchPoints?: number }): void {
    Object.defineProperty(window, 'navigator', {
      value: {
        ...originalNavigator,
        userAgent: props.userAgent ?? originalNavigator.userAgent,
        platform: props.platform ?? originalNavigator.platform,
        maxTouchPoints: props.maxTouchPoints ?? 0,
      },
      configurable: true,
      writable: true,
    });
  }

  afterEach(() => {
    Object.defineProperty(window, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
  });

  it('returns false on iOS (iPhone)', () => {
    mockNavigator({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' });
    expect(shouldAutoFocusInput()).toBe(false);
  });

  it('returns false on iPadOS 13+ (MacIntel with touch)', () => {
    mockNavigator({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      platform: 'MacIntel',
      maxTouchPoints: 5,
    });
    expect(shouldAutoFocusInput()).toBe(false);
  });

  it('returns true on desktop Mac (MacIntel without touch)', () => {
    mockNavigator({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      platform: 'MacIntel',
      maxTouchPoints: 0,
    });
    expect(shouldAutoFocusInput()).toBe(true);
  });

  it('returns true on Windows', () => {
    mockNavigator({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      platform: 'Win32',
    });
    expect(shouldAutoFocusInput()).toBe(true);
  });

  it('returns true on Android', () => {
    mockNavigator({ userAgent: 'Mozilla/5.0 (Linux; Android 14)' });
    expect(shouldAutoFocusInput()).toBe(true);
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

describe('Upload Progress UI Functions', () => {
  let sendBtn: HTMLButtonElement;

  beforeEach(() => {
    // Upload progress renders as a ring on the send/stop button
    sendBtn = document.createElement('button');
    sendBtn.id = 'send-btn';
    sendBtn.className = 'btn btn-send';
    sendBtn.setAttribute('aria-label', 'Send message');
    document.body.appendChild(sendBtn);
  });

  afterEach(() => {
    // Clean up DOM
    sendBtn.remove();
  });

  describe('showUploadProgress', () => {
    it('adds uploading class to send button', () => {
      showUploadProgress();

      expect(sendBtn.classList.contains('uploading')).toBe(true);
    });

    it('resets progress to 0%', () => {
      showUploadProgress();

      expect(sendBtn.style.getPropertyValue('--progress')).toBe('0%');
      expect(sendBtn.getAttribute('aria-label')).toBe('Uploading 0%');
    });

    it('shows indeterminate spin when progress is unknown (streaming)', () => {
      showUploadProgress(true);

      expect(sendBtn.classList.contains('uploading')).toBe(true);
      expect(sendBtn.classList.contains('processing')).toBe(true);
      expect(sendBtn.getAttribute('aria-label')).toBe('Uploading');
    });

    it('does nothing if button not found', () => {
      sendBtn.remove();

      // Should not throw
      expect(() => showUploadProgress()).not.toThrow();
    });
  });

  describe('hideUploadProgress', () => {
    it('removes uploading and processing classes', () => {
      sendBtn.classList.add('uploading', 'processing');

      hideUploadProgress();

      expect(sendBtn.classList.contains('uploading')).toBe(false);
      expect(sendBtn.classList.contains('processing')).toBe(false);
    });

    it('clears the progress custom property', () => {
      sendBtn.style.setProperty('--progress', '60%');

      hideUploadProgress();

      expect(sendBtn.style.getPropertyValue('--progress')).toBe('');
    });

    it('restores the send aria-label', () => {
      sendBtn.setAttribute('aria-label', 'Uploading 60%');

      hideUploadProgress();

      expect(sendBtn.getAttribute('aria-label')).toBe('Send message');
    });

    it('does nothing if button not found', () => {
      sendBtn.remove();

      // Should not throw
      expect(() => hideUploadProgress()).not.toThrow();
    });
  });

  describe('updateUploadProgress', () => {
    it('updates the progress custom property', () => {
      updateUploadProgress(50);

      expect(sendBtn.style.getPropertyValue('--progress')).toBe('50%');
    });

    it('announces percentage via aria-label', () => {
      updateUploadProgress(75);

      expect(sendBtn.getAttribute('aria-label')).toBe('Uploading 75%');
    });

    it('switches to indeterminate processing state at 100%', () => {
      updateUploadProgress(100);

      expect(sendBtn.classList.contains('processing')).toBe(true);
      expect(sendBtn.getAttribute('aria-label')).toBe('Processing upload');
    });

    it('leaves processing state when progress drops below 100%', () => {
      updateUploadProgress(100);
      updateUploadProgress(40);

      expect(sendBtn.classList.contains('processing')).toBe(false);
      expect(sendBtn.getAttribute('aria-label')).toBe('Uploading 40%');
    });

    it('handles 0% progress', () => {
      updateUploadProgress(0);

      expect(sendBtn.style.getPropertyValue('--progress')).toBe('0%');
      expect(sendBtn.getAttribute('aria-label')).toBe('Uploading 0%');
    });

    it('does nothing if button not found', () => {
      sendBtn.remove();

      // Should not throw
      expect(() => updateUploadProgress(50)).not.toThrow();
    });
  });
});
describe('recallLastSentMessage (up-arrow history)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<textarea id="message-input"></textarea>';
    useStore.setState({
      currentConversation: {
        id: 'c1',
        title: 'T',
        model: 'm',
        created_at: '',
        updated_at: '',
      },
      messages: new Map([
        [
          'c1',
          [
            { id: '1', role: 'user' as const, content: 'first question', created_at: '' },
            { id: '2', role: 'assistant' as const, content: 'answer', created_at: '' },
            { id: '3', role: 'user' as const, content: 'follow-up', created_at: '' },
          ],
        ],
      ]),
    });
  });

  it('fills the empty input with the last sent user message', async () => {
    const { recallLastSentMessage } = await import('@/components/MessageInput');
    const input = document.getElementById('message-input') as HTMLTextAreaElement;
    const recalled = recallLastSentMessage();
    expect(recalled).toBe(true);
    expect(input.value).toBe('follow-up');
    expect(input.selectionStart).toBe('follow-up'.length);
  });

  it('does nothing when the input already has text', async () => {
    const { recallLastSentMessage } = await import('@/components/MessageInput');
    const input = document.getElementById('message-input') as HTMLTextAreaElement;
    input.value = 'typing';
    expect(recallLastSentMessage()).toBe(false);
    expect(input.value).toBe('typing');
  });

  it('does nothing when the conversation has no user messages', async () => {
    const { recallLastSentMessage } = await import('@/components/MessageInput');
    useStore.setState({ messages: new Map([['c1', []]]) });
    expect(recallLastSentMessage()).toBe(false);
  });
});
