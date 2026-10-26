/**
 * Following a streaming reply: a restored stream that was at the bottom
 * follows new content; the user's wheel/touch or an upward scroll pauses it;
 * the scroll button or a user scroll back to the bottom re-arms it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { STREAMING_SCROLL_RESUME_DEBOUNCE_MS } from '@/config';

const setStreamingPausedIndicator = vi.fn<(paused: boolean) => void>();
let jumpToBottom: (() => void) | null = null;
vi.mock('@/components/ScrollToBottom', () => ({
  checkScrollButtonVisibility: vi.fn(),
  setStreamingPausedIndicator: (paused: boolean) => setStreamingPausedIndicator(paused),
  setOnJumpToBottom: (cb: (() => void) | null) => {
    jumpToBottom = cb;
  },
}));

type Streaming = typeof import('@/components/messages/streaming');
type Dom = typeof import('@/utils/dom');

describe('streaming follow', () => {
  let streaming: Streaming;
  let dom: Dom;
  let container: HTMLElement;
  let top: number;
  let height: number;

  /** The list moves to `scrollTop` and fires its scroll event. */
  const scrollListTo = (scrollTop: number): void => {
    top = scrollTop;
    container.dispatchEvent(new Event('scroll'));
  };

  beforeEach(async () => {
    vi.resetModules();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    setStreamingPausedIndicator.mockReset();
    jumpToBottom = null;
    document.body.innerHTML = '<div id="messages"></div>';
    container = document.getElementById('messages') as HTMLElement;
    top = 1000;
    height = 2000;
    Object.defineProperty(container, 'clientHeight', { value: 1000, configurable: true });
    Object.defineProperty(container, 'scrollHeight', { get: () => height, configurable: true });
    Object.defineProperty(container, 'scrollTop', {
      get: () => top,
      set: (v: number) => {
        top = v;
      },
      configurable: true,
    });
    container.scrollTo = ((opts: ScrollToOptions) => {
      top = Math.min(opts.top ?? top, height - 1000);
    }) as typeof container.scrollTo;
    streaming = await import('@/components/messages/streaming');
    dom = await import('@/utils/dom');
  });

  afterEach(() => {
    streaming.cleanupStreamingContext();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  /** A restored stream whose reader sat at the bottom (so it follows). */
  function following(): HTMLElement {
    const el = streaming.restoreStreamingMessage('conv-1', '');
    vi.advanceTimersByTime(1000); // let the restore's programmatic window close
    return el;
  }

  it('a restored stream that was at the bottom follows new content', async () => {
    const el = following();
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello there');
    expect(top).toBe(1600);
    const thumbs = await import('@/utils/thumbnails');
    expect(thumbs.isStreamFollowScroll(container)).toBe(true);
  });

  it('a fresh stream does not chase the reply and pulses the button once it runs past the screen', () => {
    top = 1000;
    const el = streaming.addStreamingMessage('conv-1', { anchor: false });
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello there');
    expect(top).toBe(1000);
    expect(setStreamingPausedIndicator).toHaveBeenLastCalledWith(true);
  });

  it('a wheel pauses following', async () => {
    const el = following();
    streaming.updateStreamingMessage(el, 'Hello');
    container.dispatchEvent(new Event('wheel'));
    expect(setStreamingPausedIndicator).toHaveBeenLastCalledWith(true);
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello there');
    expect(top).toBe(1000);
  });

  it('an upward scroll away from the bottom pauses following', async () => {
    const el = following();
    scrollListTo(200);
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello there');
    expect(top).toBe(200);
  });

  it('the scroll button re-arms following', async () => {
    const el = following();
    container.dispatchEvent(new Event('touchmove'));
    jumpToBottom?.();
    expect(setStreamingPausedIndicator).toHaveBeenLastCalledWith(false);
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello there');
    expect(top).toBe(1600);
  });

  it('the user scrolling back down to the bottom re-arms following after the debounce', async () => {
    const el = following();
    container.dispatchEvent(new Event('wheel'));
    scrollListTo(400);
    dom.noteUserScrollIntent();
    scrollListTo(1000);
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello');
    expect(top).toBe(1000); // not yet: debounced

    height = 2000;
    vi.advanceTimersByTime(STREAMING_SCROLL_RESUME_DEBOUNCE_MS);
    height = 2600;
    streaming.updateStreamingMessage(el, 'Hello there');
    expect(top).toBe(1600);
  });

  it('finalize reports whether the user was following and clears the pause indicator', async () => {
    const el = following();
    expect(streaming.finalizeStreamingMessage(el, 'msg-1')).toBe(true);
    expect(setStreamingPausedIndicator).toHaveBeenLastCalledWith(false);
    expect(streaming.hasActiveStreamingContext()).toBe(false);

    const paused = streaming.addStreamingMessage('conv-1', { anchor: false });
    expect(streaming.finalizeStreamingMessage(paused, 'msg-2')).toBe(false);
  });

  it('cleanup for another conversation leaves the live stream alone', () => {
    const el = streaming.addStreamingMessage('conv-1', { anchor: false });
    streaming.cleanupStreamingContext('conv-2');
    expect(streaming.getStreamingMessageElement('conv-1')).toBe(el);
    expect(streaming.getStreamingContextConversationId()).toBe('conv-1');
    streaming.cleanupStreamingContext('conv-1');
    expect(streaming.getStreamingMessageElement()).toBeNull();
  });
});
