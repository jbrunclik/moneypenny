/**
 * One scroll listener on #messages fanning out to keyed subscribers.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { offMessagesScroll, onMessagesScroll } from '@/utils/scroll-manager';

const KEYS = ['a', 'b', 'self-removing', 'replaced'];

function scroll(el: HTMLElement): void {
  el.dispatchEvent(new Event('scroll'));
}

function mountMessages(): HTMLElement {
  document.body.innerHTML = '<div id="messages"></div>';
  const container = document.getElementById('messages');
  if (!container) throw new Error('missing #messages');
  return container;
}

describe('scroll manager', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = mountMessages();
  });
  afterEach(() => {
    KEYS.forEach(offMessagesScroll);
  });

  it('dispatches a scroll to every subscriber', () => {
    const a = vi.fn();
    const b = vi.fn();
    onMessagesScroll('a', a);
    onMessagesScroll('b', b);
    scroll(container);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it('attaches a single listener however many subscribers there are', () => {
    const a = vi.fn();
    onMessagesScroll('a', a);
    onMessagesScroll('b', vi.fn());
    onMessagesScroll('a', a);
    scroll(container);
    expect(a).toHaveBeenCalledTimes(1);
  });

  it('re-subscribing under the same key replaces the subscriber', () => {
    const first = vi.fn();
    const second = vi.fn();
    onMessagesScroll('replaced', first);
    onMessagesScroll('replaced', second);
    scroll(container);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('offMessagesScroll stops delivery; unknown keys are a no-op', () => {
    const a = vi.fn();
    onMessagesScroll('a', a);
    offMessagesScroll('a');
    offMessagesScroll('never-subscribed');
    scroll(container);
    expect(a).not.toHaveBeenCalled();
  });

  it('a subscriber can unsubscribe itself during dispatch without skipping others', () => {
    const other = vi.fn();
    onMessagesScroll('self-removing', () => offMessagesScroll('self-removing'));
    onMessagesScroll('b', other);
    scroll(container);
    expect(other).toHaveBeenCalledTimes(1);
  });

  it('moves the listener to a recreated #messages on the next subscribe', () => {
    const a = vi.fn();
    onMessagesScroll('a', a);
    const oldContainer = container;
    container = mountMessages();
    onMessagesScroll('b', vi.fn());
    scroll(oldContainer);
    expect(a).not.toHaveBeenCalled();
    scroll(container);
    expect(a).toHaveBeenCalledTimes(1);
  });
});
