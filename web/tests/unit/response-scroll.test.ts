/**
 * Scroll once a reply has rendered: follow to the bottom when the user was
 * there, jump to the top of a long batch reply, and never fight a user who
 * scrolled away in between.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  atBottom: true,
  programmatic: false,
  tracked: false,
  currentId: 'conv-1' as string | null,
  checkScrollButtonVisibility: vi.fn(),
  settleTurnSpace: vi.fn(),
  enableScrollOnImageLoad: vi.fn(),
  observeThumbnail: vi.fn(),
  unobserve: vi.fn(),
  programmaticScrollToBottom: vi.fn(),
  programmaticScrollToElementTop: vi.fn(),
}));

vi.mock('@/components/ScrollToBottom', () => ({
  checkScrollButtonVisibility: mocks.checkScrollButtonVisibility,
}));
vi.mock('@/components/messages/turn-anchor', () => ({ settleTurnSpace: mocks.settleTurnSpace }));
vi.mock('@/components/messages/image-load-scroll', () => ({
  enableScrollOnImageLoad: mocks.enableScrollOnImageLoad,
}));
vi.mock('@/components/messages/thumbnail-loader', () => ({
  getThumbnailObserver: () => ({ unobserve: mocks.unobserve }),
  observeThumbnail: mocks.observeThumbnail,
}));
vi.mock('@/utils/programmatic-scroll', () => ({
  isProgrammaticScrollActive: () => mocks.programmatic,
  programmaticScrollToBottom: mocks.programmaticScrollToBottom,
  programmaticScrollToElementTop: mocks.programmaticScrollToElementTop,
}));
vi.mock('@/core/active-requests', () => ({ hasTrackedRequestFor: () => mocks.tracked }));
vi.mock('@/state/store', () => ({
  useStore: {
    getState: () => ({ currentConversation: mocks.currentId ? { id: mocks.currentId } : null }),
  },
}));
vi.mock('@/utils/dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/dom')>()),
  isScrolledToBottom: () => mocks.atBottom,
}));

import {
  handleImageScrollAfterMessage,
  scrollToBatchReply,
  settleAnchoredReply,
  settleTurnFor,
} from '@/core/response-scroll';
import { RESPONSE_JUMP_MIN_VIEWPORT_RATIO } from '@/config';

const VIEWPORT_PX = 600;
let frames: FrameRequestCallback[] = [];
let container: HTMLDivElement;
let scrollTop = 0;
let scrollHeight = 0;

/** Run the queued animation frames (and any they queue) */
function flushFrames(): void {
  while (frames.length) {
    const queued = frames;
    frames = [];
    queued.forEach((cb) => cb(0));
  }
}

function addReply(id: string, heightPx: number): HTMLElement {
  const el = document.createElement('div');
  el.dataset.messageId = id;
  Object.defineProperty(el, 'offsetHeight', { value: heightPx });
  container.appendChild(el);
  return el;
}

/** A thumbnail placeholder inside the reply, in or out of the viewport */
function addThumbnail(reply: HTMLElement, inView: boolean): HTMLImageElement {
  const img = document.createElement('img');
  img.dataset.messageId = 'm1';
  img.dataset.fileIndex = '0';
  const top = inView ? 100 : 2000;
  img.getBoundingClientRect = () => ({ top, bottom: top + 100 }) as DOMRect;
  reply.appendChild(img);
  return img;
}

function userScroll(top: number): void {
  scrollTop = top;
  container.dispatchEvent(new Event('scroll'));
}

beforeEach(() => {
  frames = [];
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    frames.push(cb);
    return frames.length;
  });
  container = document.createElement('div');
  container.id = 'messages';
  scrollTop = 1000;
  Object.defineProperty(container, 'scrollTop', { get: () => scrollTop, set: (v: number) => (scrollTop = v) });
  scrollHeight = 5000;
  Object.defineProperty(container, 'scrollHeight', { get: () => scrollHeight });
  Object.defineProperty(container, 'clientHeight', { value: VIEWPORT_PX });
  container.getBoundingClientRect = () => ({ top: 0, bottom: VIEWPORT_PX }) as DOMRect;
  document.body.appendChild(container);
  Object.assign(mocks, { atBottom: true, programmatic: false, tracked: false, currentId: 'conv-1' });
  vi.clearAllMocks();
});

afterEach(() => {
  container.remove();
  vi.unstubAllGlobals();
});

describe('handleImageScrollAfterMessage', () => {
  it('does nothing without files', () => {
    handleImageScrollAfterMessage(addReply('m1', 100), undefined);
    handleImageScrollAfterMessage(addReply('m2', 100), null);
    flushFrames();
    expect(mocks.programmaticScrollToBottom).not.toHaveBeenCalled();
    expect(mocks.checkScrollButtonVisibility).not.toHaveBeenCalled();
  });

  it('keeps a user at the bottom pinned while server images load', () => {
    const reply = addReply('m1', 100);
    const visible = addThumbnail(reply, true);
    addThumbnail(reply, false);
    handleImageScrollAfterMessage(reply, [{ type: 'image/png' }]);
    expect(mocks.enableScrollOnImageLoad).toHaveBeenCalled();
    expect(mocks.programmaticScrollToBottom).toHaveBeenCalledWith(container, false);
    flushFrames();
    // Only the thumbnail in view starts loading now
    expect(mocks.observeThumbnail).toHaveBeenCalledTimes(1);
    expect(mocks.observeThumbnail).toHaveBeenCalledWith(visible);
    expect(mocks.checkScrollButtonVisibility).toHaveBeenCalled();
  });

  it('scrolls a user at the bottom down for files that need no loading', () => {
    // A local preview (blob URL) or a non-image is already laid out
    handleImageScrollAfterMessage(addReply('m1', 100), [
      { type: 'image/png', previewUrl: 'blob:x' },
      { type: 'application/pdf' },
    ]);
    expect(mocks.enableScrollOnImageLoad).not.toHaveBeenCalled();
    expect(mocks.programmaticScrollToBottom).toHaveBeenCalledWith(container);
  });

  it('leaves a user who scrolled away where they are', () => {
    mocks.atBottom = false;
    handleImageScrollAfterMessage(addReply('m1', 100), [{ type: 'image/png' }]);
    flushFrames();
    expect(mocks.programmaticScrollToBottom).not.toHaveBeenCalled();
    expect(mocks.enableScrollOnImageLoad).not.toHaveBeenCalled();
    expect(mocks.checkScrollButtonVisibility).toHaveBeenCalled();
  });
});

describe('settleAnchoredReply', () => {
  it('gives back the turn space and starts the images in view, without scrolling', () => {
    const reply = addReply('m1', 2000);
    addThumbnail(reply, true);
    settleAnchoredReply(container, reply);
    expect(mocks.settleTurnSpace).toHaveBeenCalledWith(container);
    flushFrames();
    expect(mocks.observeThumbnail).toHaveBeenCalledTimes(1);
    expect(mocks.programmaticScrollToBottom).not.toHaveBeenCalled();
    expect(mocks.programmaticScrollToElementTop).not.toHaveBeenCalled();
  });
});

describe('scrollToBatchReply', () => {
  it('jumps to the top of a reply taller than the viewport', () => {
    const reply = addReply('m1', VIEWPORT_PX * RESPONSE_JUMP_MIN_VIEWPORT_RATIO + 1);
    scrollToBatchReply(container, 'm1', false);
    flushFrames();
    expect(mocks.programmaticScrollToElementTop).toHaveBeenCalledWith(container, reply, true);
    expect(mocks.programmaticScrollToBottom).not.toHaveBeenCalled();
  });

  it('scrolls a short reply into view at the bottom instead', () => {
    addReply('m1', VIEWPORT_PX * RESPONSE_JUMP_MIN_VIEWPORT_RATIO);
    scrollToBatchReply(container, 'm1', false);
    flushFrames();
    expect(mocks.programmaticScrollToBottom).toHaveBeenCalledWith(container);
    expect(mocks.programmaticScrollToElementTop).not.toHaveBeenCalled();
  });

  it('respects a user scroll up before the frame, even a tiny one', () => {
    addReply('m1', 5000);
    scrollToBatchReply(container, 'm1', false);
    userScroll(995);
    flushFrames();
    expect(mocks.programmaticScrollToElementTop).not.toHaveBeenCalled();
    expect(mocks.programmaticScrollToBottom).not.toHaveBeenCalled();
    expect(mocks.checkScrollButtonVisibility).toHaveBeenCalled();
  });

  it('respects a position that moved far without a scroll event', () => {
    addReply('m1', 5000);
    scrollToBatchReply(container, 'm1', false);
    scrollTop = 1100; // scroll anchoring would not fire as a user scroll-up
    flushFrames();
    expect(mocks.programmaticScrollToElementTop).not.toHaveBeenCalled();
  });

  it('does not count our own scrolls or the bottom clamp as a user scroll', () => {
    addReply('m1', 5000);
    scrollToBatchReply(container, 'm1', false);
    mocks.programmatic = true;
    userScroll(990);
    mocks.programmatic = false;
    // The finalized list is shorter: the browser clamps scrollTop up to
    // the new bottom (moves up, but leaves no gap)
    scrollHeight = 980 + VIEWPORT_PX;
    userScroll(980);
    flushFrames();
    expect(mocks.programmaticScrollToElementTop).toHaveBeenCalled();
  });

  it('starts the images in view once it has jumped', () => {
    const reply = addReply('m1', 5000);
    addThumbnail(reply, true);
    scrollToBatchReply(container, 'm1', true);
    flushFrames();
    expect(mocks.observeThumbnail).toHaveBeenCalledTimes(1);
  });

  it('only refreshes the scroll button when the reply is not in the list', () => {
    scrollToBatchReply(container, 'missing', false);
    flushFrames();
    expect(mocks.programmaticScrollToElementTop).not.toHaveBeenCalled();
    expect(mocks.checkScrollButtonVisibility).toHaveBeenCalled();
  });
});

describe('settleTurnFor', () => {
  it('gives back the turn space of the open conversation', () => {
    settleTurnFor('conv-1');
    expect(mocks.settleTurnSpace).toHaveBeenCalledWith(container);
  });

  it('leaves another conversation alone', () => {
    settleTurnFor('conv-2');
    expect(mocks.settleTurnSpace).not.toHaveBeenCalled();
  });

  it('leaves the space to a newer turn that started meanwhile', () => {
    mocks.tracked = true;
    settleTurnFor('conv-1');
    expect(mocks.settleTurnSpace).not.toHaveBeenCalled();
  });
});
