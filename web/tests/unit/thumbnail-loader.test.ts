/**
 * Thumbnail lazy loading: the IntersectionObserver hands visible images to a
 * concurrency-limited fetch queue, which sets a blob URL, marks the image
 * loaded (or errored) and revokes the URL once the image leaves the DOM or
 * the conversation changes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { THUMBNAIL_MAX_CONCURRENT_FETCHES } from '@/config';

const fetchThumbnail = vi.fn<(messageId: string, index: number) => Promise<Blob>>();
vi.mock('@/api/files', () => ({
  files: { fetchThumbnail: (id: string, index: number) => fetchThumbnail(id, index) },
}));

class FakeIntersectionObserver {
  static last: FakeIntersectionObserver | null = null;
  observed = new Set<Element>();
  constructor(private readonly callback: IntersectionObserverCallback) {
    FakeIntersectionObserver.last = this;
  }
  observe(el: Element): void {
    this.observed.add(el);
  }
  unobserve(el: Element): void {
    this.observed.delete(el);
  }
  disconnect(): void {
    this.observed.clear();
  }
  /** The element scrolled into view. */
  intersect(el: Element): void {
    this.callback(
      [{ isIntersecting: true, target: el } as unknown as IntersectionObserverEntry],
      this as unknown as IntersectionObserver
    );
  }
}

type Loader = typeof import('@/utils/thumbnails');
type BlobUrls = typeof import('@/utils/thumbnail-blob-urls');

const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

function image(messageId: string, index: number): HTMLImageElement {
  const wrapper = document.createElement('div');
  wrapper.className = 'message-image-wrapper loading';
  const img = document.createElement('img');
  img.className = 'loading';
  img.dataset.messageId = messageId;
  img.dataset.fileIndex = String(index);
  wrapper.appendChild(img);
  document.getElementById('messages')?.appendChild(wrapper);
  return img;
}

describe('thumbnail loader', () => {
  let loader: Loader;
  let blobUrls: BlobUrls;
  let urlCount: number;

  beforeEach(async () => {
    vi.resetModules();
    fetchThumbnail.mockReset();
    urlCount = 0;
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
    URL.createObjectURL = vi.fn(() => `blob:thumb-${++urlCount}`);
    URL.revokeObjectURL = vi.fn();
    document.body.innerHTML = '<div id="messages"></div>';
    loader = await import('@/utils/thumbnails');
    blobUrls = await import('@/utils/thumbnail-blob-urls');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function io(): FakeIntersectionObserver {
    const observer = FakeIntersectionObserver.last;
    if (!observer) throw new Error('no observer created');
    return observer;
  }

  it('observes an image and fetches it once it is visible', async () => {
    fetchThumbnail.mockResolvedValue(new Blob(['x']));
    const img = image('m1', 2);
    loader.observeThumbnail(img);
    expect(io().observed.has(img)).toBe(true);

    io().intersect(img);
    expect(io().observed.has(img)).toBe(false);
    await flush();
    expect(fetchThumbnail).toHaveBeenCalledWith('m1', 2);
    expect(img.src).toBe('blob:thumb-1');
  });

  it('marks the image loaded once its load event fires', async () => {
    fetchThumbnail.mockResolvedValue(new Blob(['x']));
    const img = image('m1', 0);
    loader.observeThumbnail(img);
    io().intersect(img);
    await flush();
    expect(img.classList.contains('loaded')).toBe(false);

    img.dispatchEvent(new Event('load'));
    await flush();
    expect(img.classList.contains('loaded')).toBe(true);
    expect(img.classList.contains('loading')).toBe(false);
    expect(img.parentElement?.classList.contains('loading')).toBe(false);
  });

  it('marks the image and its wrapper errored when the fetch fails', async () => {
    fetchThumbnail.mockRejectedValue(new Error('404'));
    const img = image('m1', 0);
    loader.observeThumbnail(img);
    io().intersect(img);
    await flush();
    expect(img.classList.contains('error')).toBe(true);
    expect(img.classList.contains('loading')).toBe(false);
    expect(img.parentElement?.classList.contains('error')).toBe(true);
    expect(img.parentElement?.classList.contains('loading')).toBe(false);
  });

  it(`fetches at most ${THUMBNAIL_MAX_CONCURRENT_FETCHES} thumbnails at once`, async () => {
    const pending: Array<(blob: Blob) => void> = [];
    fetchThumbnail.mockImplementation(() => new Promise<Blob>((resolve) => pending.push(resolve)));
    const images = Array.from({ length: THUMBNAIL_MAX_CONCURRENT_FETCHES + 2 }, (_, i) => image('m1', i));
    images.forEach((img) => {
      loader.observeThumbnail(img);
      io().intersect(img);
    });
    await flush();
    expect(fetchThumbnail).toHaveBeenCalledTimes(THUMBNAIL_MAX_CONCURRENT_FETCHES);

    pending[0]?.(new Blob(['x']));
    await flush();
    images[0]?.dispatchEvent(new Event('load'));
    await flush();
    expect(fetchThumbnail).toHaveBeenCalledTimes(THUMBNAIL_MAX_CONCURRENT_FETCHES + 1);
  });

  it('does not observe while observation is deferred', () => {
    const img = image('m1', 0);
    loader.setDeferImageObservation(true);
    loader.observeThumbnail(img);
    expect(FakeIntersectionObserver.last?.observed.has(img) ?? false).toBe(false);
    loader.setDeferImageObservation(false);
    loader.observeThumbnail(img);
    expect(io().observed.has(img)).toBe(true);
  });

  it('revokes the blob URL when the image leaves the DOM', async () => {
    fetchThumbnail.mockResolvedValue(new Blob(['x']));
    const img = image('m1', 0);
    loader.observeThumbnail(img);
    io().intersect(img);
    await flush();
    img.dispatchEvent(new Event('load'));
    await flush();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();

    img.remove();
    await flush();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:thumb-1');
  });

  it('revokes the open conversation blob URLs when switching to another conversation', async () => {
    fetchThumbnail.mockResolvedValue(new Blob(['x']));
    blobUrls.setCurrentConversationForBlobs('conv-a');
    const img = image('m1', 0);
    loader.observeThumbnail(img);
    io().intersect(img);
    await flush();

    blobUrls.setCurrentConversationForBlobs('conv-a');
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    blobUrls.setCurrentConversationForBlobs('conv-b');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:thumb-1');
  });

  it('cleanupBlobUrl revokes blob URLs only', () => {
    blobUrls.cleanupBlobUrl('https://example.com/a.png');
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    blobUrls.cleanupBlobUrl('blob:abc');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:abc');
  });
});
