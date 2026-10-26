/**
 * The image-load chase: while armed, the list glides to the bottom once every
 * tracked (visible) image has loaded - three animation frames after the last
 * load, so layout settles first - unless the user genuinely scrolled up.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IMAGE_LOAD_RETRY_DELAY_MS } from '@/config';

const fetchThumbnail = vi.fn<(messageId: string, index: number) => Promise<Blob>>();
vi.mock('@/api/files', () => ({
  files: { fetchThumbnail: (id: string, index: number) => fetchThumbnail(id, index) },
}));

const scrollToBottom = vi.fn<(el: HTMLElement, smooth?: boolean, onDone?: () => void) => void>();
vi.mock('@/utils/dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/dom')>();
  return {
    ...actual,
    scrollToBottom: (el: HTMLElement, smooth?: boolean, onDone?: () => void) => scrollToBottom(el, smooth, onDone),
  };
});

const checkScrollButtonVisibility = vi.fn();
vi.mock('@/components/ScrollToBottom', () => ({
  checkScrollButtonVisibility: () => checkScrollButtonVisibility(),
}));

class FakeIntersectionObserver {
  static last: FakeIntersectionObserver | null = null;
  constructor(private readonly callback: IntersectionObserverCallback) {
    FakeIntersectionObserver.last = this;
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  intersect(el: Element): void {
    this.callback(
      [{ isIntersecting: true, target: el } as unknown as IntersectionObserverEntry],
      this as unknown as IntersectionObserver
    );
  }
}

type Thumbs = typeof import('@/utils/thumbnails');

let frames = new Map<number, FrameRequestCallback>();
let nextFrameId = 0;
/** Run `n` rounds of animation frames (each round runs what was queued before it). */
function runFrames(n: number): void {
  for (let i = 0; i < n; i++) {
    const round = [...frames.values()];
    frames = new Map();
    round.forEach((cb) => cb(0));
  }
}

const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

function image(index: number, { loaded = false }: { loaded?: boolean } = {}): HTMLImageElement {
  const img = document.createElement('img');
  img.dataset.messageId = 'm1';
  img.dataset.fileIndex = String(index);
  if (loaded) {
    img.src = `blob:cached-${index}`;
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
  }
  document.getElementById('messages')?.appendChild(img);
  return img;
}

/** The fetched image finished decoding. */
function finishLoad(img: HTMLImageElement): void {
  Object.defineProperty(img, 'complete', { value: true, configurable: true });
  img.dispatchEvent(new Event('load'));
}

describe('image-load chase scheduling', () => {
  let thumbs: Thumbs;
  let container: HTMLElement;

  beforeEach(async () => {
    vi.resetModules();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    frames = new Map();
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      frames.set(++nextFrameId, cb);
      return nextFrameId;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
    URL.createObjectURL = vi.fn(() => 'blob:thumb');
    URL.revokeObjectURL = vi.fn();
    fetchThumbnail.mockReset();
    scrollToBottom.mockReset();
    checkScrollButtonVisibility.mockReset();
    document.body.innerHTML = '<div id="messages"></div>';
    container = document.getElementById('messages') as HTMLElement;
    Object.defineProperty(container, 'scrollHeight', { value: 3000, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 1000, configurable: true });
    container.scrollTop = 2000; // pinned to the bottom
    thumbs = await import('@/utils/thumbnails');
  });

  afterEach(() => {
    thumbs.disableScrollOnImageLoad();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function io(): FakeIntersectionObserver {
    const observer = FakeIntersectionObserver.last;
    if (!observer) throw new Error('no observer created');
    return observer;
  }

  it('glides to the bottom on the third frame after the last image loads', async () => {
    fetchThumbnail.mockResolvedValue(new Blob(['x']));
    thumbs.enableScrollOnImageLoad();
    const img = image(0);
    thumbs.observeThumbnail(img);
    io().intersect(img);
    await flush();
    finishLoad(img);
    await flush();

    runFrames(2);
    expect(scrollToBottom).not.toHaveBeenCalled();
    runFrames(1);
    expect(scrollToBottom).toHaveBeenCalledTimes(1);
    expect(scrollToBottom).toHaveBeenCalledWith(container, true, expect.any(Function));
    expect(thumbs.isProgrammaticScrollActive()).toBe(true);

    runFrames(1);
    expect(checkScrollButtonVisibility).toHaveBeenCalled();
  });

  it('waits for every tracked image before gliding', async () => {
    fetchThumbnail.mockResolvedValue(new Blob(['x']));
    thumbs.enableScrollOnImageLoad();
    const first = image(0);
    const second = image(1);
    [first, second].forEach((img) => {
      thumbs.observeThumbnail(img);
      io().intersect(img);
    });
    await flush();
    finishLoad(first);
    await flush();
    runFrames(10);
    expect(scrollToBottom).not.toHaveBeenCalled();

    finishLoad(second);
    await flush();
    runFrames(10);
    expect(scrollToBottom).toHaveBeenCalledTimes(1);
  });

  it('counts already-loaded (cached) images and glides', () => {
    thumbs.enableScrollOnImageLoad();
    image(0, { loaded: true });
    image(1, { loaded: true });
    thumbs.countVisibleImagesForScroll();
    runFrames(3);
    expect(scrollToBottom).toHaveBeenCalledWith(container, true, expect.any(Function));
  });

  it('does nothing when the chase is off', () => {
    image(0, { loaded: true });
    thumbs.countVisibleImagesForScroll();
    runFrames(5);
    expect(scrollToBottom).not.toHaveBeenCalled();
  });

  it('switches off instead of gliding when the user scrolled well above the bottom', () => {
    thumbs.enableScrollOnImageLoad();
    image(0, { loaded: true });
    container.scrollTop = 500; // far above the followed bottom, no scroll event seen
    thumbs.countVisibleImagesForScroll();
    runFrames(5);
    expect(scrollToBottom).not.toHaveBeenCalled();
    expect(thumbs.isScrollOnImageLoadEnabled()).toBe(false);
  });

  it('a disable before the frames run cancels the glide', () => {
    thumbs.enableScrollOnImageLoad();
    image(0, { loaded: true });
    thumbs.countVisibleImagesForScroll();
    runFrames(1);
    thumbs.disableScrollOnImageLoad();
    runFrames(5);
    expect(scrollToBottom).not.toHaveBeenCalled();
  });

  it('a failed fetch leaves its image unloaded, so the chase retries and never glides', async () => {
    fetchThumbnail.mockRejectedValue(new Error('404'));
    thumbs.enableScrollOnImageLoad();
    const img = image(0);
    thumbs.observeThumbnail(img);
    io().intersect(img);
    await flush();
    vi.advanceTimersByTime(IMAGE_LOAD_RETRY_DELAY_MS * 5);
    runFrames(10);
    expect(scrollToBottom).not.toHaveBeenCalled();
    expect(thumbs.isScrollOnImageLoadEnabled()).toBe(true);
  });
});
