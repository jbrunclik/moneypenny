/**
 * Unit tests for the composer-height publisher (--composer-height).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanupComposerHeight, initComposerHeight } from '@/core/composer-height';
import { programmaticScrollToBottom } from '@/utils/thumbnails';
import { isScrolledToBottom } from '@/utils/dom';

vi.mock('@/utils/thumbnails', () => ({ programmaticScrollToBottom: vi.fn() }));
vi.mock('@/utils/dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/dom')>();
  return { ...actual, isScrolledToBottom: vi.fn() };
});

function getVar(): string {
  return document.documentElement.style.getPropertyValue('--composer-height');
}

describe('composer height', () => {
  let inputArea: HTMLDivElement;

  beforeEach(() => {
    document.body.innerHTML = '<div class="input-area"></div>';
    inputArea = document.querySelector('.input-area') as HTMLDivElement;
    // jsdom has no layout - stub the rects. No .input-container child here, so
    // the pill falls back to inputArea; footprint = bottom - top = 72.
    vi.spyOn(inputArea, 'getBoundingClientRect').mockReturnValue({
      top: 0,
      bottom: 72,
      height: 72,
    } as DOMRect);
  });

  afterEach(() => {
    cleanupComposerHeight();
  });

  it('publishes the composer height on init', () => {
    initComposerHeight();
    expect(getVar()).toBe('72px');
  });

  it('does nothing when there is no composer', () => {
    document.body.innerHTML = '';
    initComposerHeight();
    expect(getVar()).toBe('');
  });

  it('clears the variable on cleanup', () => {
    initComposerHeight();
    expect(getVar()).toBe('72px');
    cleanupComposerHeight();
    expect(getVar()).toBe('');
  });
});

describe('composer height re-pin', () => {
  let inputArea: HTMLDivElement;
  let rect: { top: number; bottom: number; height: number };
  let resizeCallback: (() => void) | null;

  beforeEach(() => {
    document.body.innerHTML = '<div id="messages"></div><div class="input-area"></div>';
    inputArea = document.querySelector('.input-area') as HTMLDivElement;
    rect = { top: 0, bottom: 72, height: 72 };
    vi.spyOn(inputArea, 'getBoundingClientRect').mockImplementation(() => rect as DOMRect);
    resizeCallback = null;
    // jsdom has no ResizeObserver - capture the callback so a test can fire it
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: () => void) {
          resizeCallback = cb;
        }
        observe(): void {}
        disconnect(): void {}
      }
    );
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
    vi.mocked(isScrolledToBottom).mockReturnValue(true);
    vi.mocked(programmaticScrollToBottom).mockClear();
  });

  afterEach(() => {
    cleanupComposerHeight();
    vi.unstubAllGlobals();
  });

  it('re-pins a bottom-scrolled list when the composer grows', () => {
    initComposerHeight(); // the initial measure (0 -> 72) re-pins too
    vi.mocked(programmaticScrollToBottom).mockClear();
    rect = { top: 0, bottom: 120, height: 120 };
    resizeCallback?.();
    expect(getVar()).toBe('120px');
    expect(programmaticScrollToBottom).toHaveBeenCalledTimes(1);
  });

  it('does not re-pin when the composer shrinks or is hidden by a non-chat view', () => {
    // Storage/Agents hide the composer; re-pinning here raced the view's own
    // render and dropped the user at the bottom of a page that starts at the top
    initComposerHeight();
    vi.mocked(programmaticScrollToBottom).mockClear();
    rect = { top: 0, bottom: 0, height: 0 };
    resizeCallback?.();
    expect(getVar()).toBe('0px');
    expect(programmaticScrollToBottom).not.toHaveBeenCalled();
  });

  it('does not re-pin when the list was not following the bottom', () => {
    vi.mocked(isScrolledToBottom).mockReturnValue(false);
    initComposerHeight();
    vi.mocked(programmaticScrollToBottom).mockClear();
    rect = { top: 0, bottom: 120, height: 120 };
    resizeCallback?.();
    expect(programmaticScrollToBottom).not.toHaveBeenCalled();
  });
});
