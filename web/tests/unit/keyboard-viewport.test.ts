/**
 * Unit tests for mobile keyboard viewport pinning (--keyboard-inset).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initKeyboardViewportPinning } from '@/core/keyboard-viewport';

// The re-pin path calls element.scrollTo, which jsdom doesn't implement -
// without the stub the deferred RAF throws an uncaught async exception
Element.prototype.scrollTo = vi.fn();

class MockVisualViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function getInset(): string {
  return document.documentElement.style.getPropertyValue('--keyboard-inset');
}

describe('keyboard viewport pinning', () => {
  let viewport: MockVisualViewport;
  let textarea: HTMLTextAreaElement;

  beforeEach(() => {
    document.body.innerHTML = '<div id="messages"></div><textarea id="message-input"></textarea>';
    document.documentElement.style.removeProperty('--keyboard-inset');
    viewport = new MockVisualViewport();
    Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    textarea = document.getElementById('message-input') as HTMLTextAreaElement;
    initKeyboardViewportPinning();
  });

  it('sets the keyboard inset when the viewport shrinks with an input focused', () => {
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');
  });

  it('ignores small shrinks below the keyboard threshold (accessory bars)', () => {
    textarea.focus();
    viewport.height = 760; // 40px < KEYBOARD_INSET_MIN_PX
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('resets the stale layout-viewport pan and redraws the caret on inset', async () => {
    // Standalone-PWA caret bug: iOS pans the layout viewport to reveal a
    // focused bottom input; our height shrink then reflows content up but
    // WebKit keeps drawing the caret at the stale pan position (outside
    // the input). Reset the pan and re-assert the selection to force a
    // caret redraw.
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.value = 'hello';
    textarea.focus();
    textarea.setSelectionRange(3, 3);
    const selectionSpy = vi.spyOn(textarea, 'setSelectionRange');

    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();

    expect(scrollToSpy).toHaveBeenCalledWith(0, 0);
    // Caret redraw nudge preserves the existing caret position
    expect(selectionSpy).toHaveBeenCalledWith(3, 3);
    scrollToSpy.mockRestore();
  });

  it('does not touch scroll or selection when no inset applies', async () => {
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    viewport.height = 760; // below threshold - no inset
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();

    expect(scrollToSpy).not.toHaveBeenCalled();
    scrollToSpy.mockRestore();
  });

  it('does not thrash layout when the user pans with the keyboard open', async () => {
    // Welcome-screen lag: with no inner scroll container, drags pan the
    // visual viewport (offsetTop churns per pixel). The inset must depend
    // only on keyboard GEOMETRY (height), never on the pan position -
    // otherwise every pan pixel reflows the whole page mid-gesture.
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();
    expect(getInset()).toBe('300px');
    const scrollToCallsAfterOpen = scrollToSpy.mock.calls.length;

    const setPropertySpy = vi.spyOn(document.documentElement.style, 'setProperty');
    for (let offset = 1; offset <= 30; offset++) {
      viewport.offsetTop = offset;
      viewport.dispatchEvent(new Event('scroll'));
    }
    await nextFrame();
    await nextFrame();

    expect(getInset()).toBe('300px'); // unchanged by panning
    expect(setPropertySpy).not.toHaveBeenCalled(); // zero mid-gesture reflows
    expect(scrollToSpy.mock.calls.length).toBe(scrollToCallsAfterOpen); // no pan fighting
    scrollToSpy.mockRestore();
  });

  it('runs the caret nudge only on the keyboard-open transition', async () => {
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();
    expect(scrollToSpy).toHaveBeenCalledTimes(1);

    // Keyboard geometry fluctuation while open (accessory bar toggle)
    viewport.height = 540;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    await nextFrame();

    expect(getInset()).toBe('260px'); // inset tracks geometry
    expect(scrollToSpy).toHaveBeenCalledTimes(1); // but no re-nudge
    scrollToSpy.mockRestore();
  });

  it('ignores pinch zoom (scale != 1)', () => {
    textarea.focus();
    viewport.scale = 2;
    viewport.height = 400;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('ignores shrinks when no editable element is focused', () => {
    textarea.blur();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('clears the inset when focus leaves the input', async () => {
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');

    viewport.height = 800;
    textarea.blur();
    document.dispatchEvent(new Event('focusout'));
    await nextFrame();
    expect(getInset()).toBe('0px');
  });

  it('blocks viewport-panning touchmoves while the keyboard is open', async () => {
    // iOS pans the visual viewport within the full-height layout viewport
    // when the keyboard is open - on the welcome screen (nothing scrollable)
    // that pan rubber-bands the whole page ("jumping"). Touchmoves that no
    // scrollable element can consume must be prevented while inset > 0.
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();

    const welcome = document.createElement('div');
    document.body.appendChild(welcome);
    const evt = new Event('touchmove', { bubbles: true, cancelable: true });
    welcome.dispatchEvent(evt);
    expect(evt.defaultPrevented).toBe(true);
  });

  it('allows touchmoves inside a scrollable messages container', async () => {
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();

    const messages = document.getElementById('messages') as HTMLDivElement;
    messages.style.overflowY = 'auto';
    Object.defineProperty(messages, 'scrollHeight', { value: 2000, configurable: true });
    Object.defineProperty(messages, 'clientHeight', { value: 400, configurable: true });
    const inner = document.createElement('div');
    messages.appendChild(inner);

    const evt = new Event('touchmove', { bubbles: true, cancelable: true });
    inner.dispatchEvent(evt);
    expect(evt.defaultPrevented).toBe(false);
  });

  it('stops blocking touchmoves once the keyboard closes', async () => {
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();
    viewport.height = 800;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();

    const evt = new Event('touchmove', { bubbles: true, cancelable: true });
    document.body.dispatchEvent(evt);
    expect(evt.defaultPrevented).toBe(false);
  });

  it('derives the inset from keyboard geometry alone, ignoring pan offset', () => {
    // offsetTop deliberately does NOT participate: pan-dependent insets
    // reflow the page per pan pixel (welcome-screen lag). The focus-pan
    // is reset via scrollTo(0,0) on the open transition instead.
    textarea.focus();
    viewport.height = 500;
    viewport.offsetTop = 100;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');
  });
});
