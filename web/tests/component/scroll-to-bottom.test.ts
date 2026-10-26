import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/utils/dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/dom')>()),
  scrollToBottom: vi.fn(),
  cancelSmoothScroll: vi.fn(),
  noteUserScrollIntent: vi.fn(),
}));

import { cancelSmoothScroll, scrollToBottom } from '@/utils/dom';
import {
  checkScrollButtonVisibility,
  clearNewMessagesPill,
  initScrollToBottom,
  setBeforeScrollToBottomCallback,
  setOnJumpToBottom,
  setStreamingPausedIndicator,
  showNewMessagesPill,
} from '@/components/ScrollToBottom';
import { SCROLL_BUTTON_SHOW_THRESHOLD_PX } from '@/config';

const button = () => document.querySelector<HTMLButtonElement>('.scroll-to-bottom')!;
const messages = () => document.getElementById('messages')!;

/** Place the list `below` px above its bottom. */
function scrolledUp(below: number): void {
  Object.defineProperty(messages(), 'scrollHeight', { value: 2000, configurable: true });
  Object.defineProperty(messages(), 'clientHeight', { value: 500, configurable: true });
  messages().scrollTop = 1500 - below;
}

async function tap(): Promise<void> {
  button().click();
  await vi.waitFor(() => expect(scrollToBottom).toHaveBeenCalled());
}

describe('ScrollToBottom', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div class="main"><div id="messages"></div><div id="composer"></div></div>';
    vi.mocked(scrollToBottom).mockClear();
    vi.mocked(cancelSmoothScroll).mockClear();
    setBeforeScrollToBottomCallback(null);
    setOnJumpToBottom(null);
    initScrollToBottom();
  });

  it('sits right after the message list, hidden', () => {
    expect(messages().nextElementSibling).toBe(button());
    expect(button().classList.contains('hidden')).toBe(true);
    expect(button().getAttribute('aria-label')).toBe('Scroll to bottom');
  });

  it('shows once the user is further up than the threshold, hides at the bottom', () => {
    scrolledUp(SCROLL_BUTTON_SHOW_THRESHOLD_PX + 50);
    checkScrollButtonVisibility();
    expect(button().classList.contains('hidden')).toBe(false);

    scrolledUp(0);
    checkScrollButtonVisibility();
    expect(button().classList.contains('hidden')).toBe(true);
  });

  it('a tap loads the rest first, re-arms follow mode, then smooth-scrolls', async () => {
    const order: string[] = [];
    setBeforeScrollToBottomCallback(async () => {
      order.push('load');
    });
    setOnJumpToBottom(() => order.push('jump'));
    vi.mocked(scrollToBottom).mockImplementation(() => {
      order.push('scroll');
    });

    await tap();

    expect(order).toEqual(['load', 'jump', 'scroll']);
    expect(vi.mocked(scrollToBottom).mock.calls[0]![1]).toBe(true);
  });

  it('still scrolls when loading the rest fails', async () => {
    setBeforeScrollToBottomCallback(() => Promise.reject(new Error('offline')));
    await tap();
    expect(scrollToBottom).toHaveBeenCalledOnce();
  });

  it('ignores a second tap while the first still loads', async () => {
    let finish!: () => void;
    const load = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    setBeforeScrollToBottomCallback(load);

    button().click();
    button().click();
    finish();
    await vi.waitFor(() => expect(scrollToBottom).toHaveBeenCalled());

    expect(load).toHaveBeenCalledOnce();
    expect(scrollToBottom).toHaveBeenCalledOnce();
  });

  it('turns into the New messages pill until the user reaches the bottom', () => {
    scrolledUp(SCROLL_BUTTON_SHOW_THRESHOLD_PX + 50);
    showNewMessagesPill();
    expect(button().classList.contains('has-new-messages')).toBe(true);
    expect(button().classList.contains('hidden')).toBe(false);

    scrolledUp(0);
    checkScrollButtonVisibility();
    expect(button().classList.contains('has-new-messages')).toBe(false);
  });

  it('drops the pill on a conversation switch', () => {
    scrolledUp(SCROLL_BUTTON_SHOW_THRESHOLD_PX + 50);
    showNewMessagesPill();
    clearNewMessagesPill();
    expect(button().classList.contains('has-new-messages')).toBe(false);
  });

  it('pulses while a paused stream writes below', () => {
    setStreamingPausedIndicator(true);
    expect(button().classList.contains('streaming-paused')).toBe(true);
    setStreamingPausedIndicator(false);
    expect(button().classList.contains('streaming-paused')).toBe(false);
  });

  it('a wheel or scroll key takes over from our smooth scroll, typing does not', () => {
    // Earlier tests' inits left document key listeners too: compare counts
    const calls = () => vi.mocked(cancelSmoothScroll).mock.calls.length;
    messages().dispatchEvent(new WheelEvent('wheel'));
    expect(calls()).toBe(1);

    let before = calls();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageUp' }));
    expect(calls()).toBeGreaterThan(before);

    const input = document.createElement('textarea');
    document.body.appendChild(input);
    before = calls();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    expect(calls()).toBe(before);
  });
});
