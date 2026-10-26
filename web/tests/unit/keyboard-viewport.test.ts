/**
 * Unit tests for mobile keyboard viewport pinning (--keyboard-inset).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  cleanupKeyboardViewportPinning,
  initKeyboardViewportPinning,
} from '@/core/keyboard-viewport';

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

  afterEach(() => {
    cleanupKeyboardViewportPinning();
    vi.useRealTimers();
  });

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

  it('applies the inset when resize fires before focus lands (focusin re-check)', async () => {
    // iOS can fire the viewport resize BEFORE document.activeElement is
    // the textarea - an AMBIGUOUS shrink (below the definite threshold)
    // is then ignored, and nothing re-triggers. focusin must re-check.
    viewport.height = 680; // 120px - above inset min, below definite
    viewport.dispatchEvent(new Event('resize')); // no editable focused yet
    expect(getInset()).toBe('');

    textarea.focus();
    document.dispatchEvent(new Event('focusin'));
    await nextFrame();

    expect(getInset()).toBe('120px');
  });

  it('treats a large shrink as keyboard even without a focused editable', () => {
    // A 300px shrink is unambiguously a keyboard - browser chrome
    // show/hide is far smaller. Without this, a focus-detection miss
    // leaves the composer hidden behind the keyboard.
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');
  });

  it('still ignores small shrinks without a focused editable', () => {
    viewport.height = 690; // 110px - could be browser chrome
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('ignores pinch zoom (scale != 1)', () => {
    textarea.focus();
    viewport.scale = 2;
    viewport.height = 400;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('ignores ambiguous shrinks when no editable element is focused', () => {
    // Below KEYBOARD_DEFINITE_SHRINK_PX a shrink could be browser chrome -
    // without a focused editable it is ignored. (Large shrinks are treated
    // as keyboard regardless; see the definite-shrink test.)
    textarea.blur();
    viewport.height = 690; // 110px shrink - ambiguous
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('');
  });

  it('adds the accessory-pill height to the inset in standalone display', () => {
    // Standalone PWAs: the visual viewport excludes only the keyboard;
    // iOS's floating input-assistant pill hovers over the composer
    // unreported and must be cleared via a constant.
    Object.defineProperty(navigator, 'standalone', { value: true, configurable: true });
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    const inset = getInset();
    Object.defineProperty(navigator, 'standalone', { value: undefined, configurable: true });
    expect(inset).toBe('350px'); // 300 keyboard + 50 accessory pill
  });

  it('toggles the kb-open root class with the inset', async () => {
    // CSS uses :root.kb-open to reclaim padding that is pointless while
    // the keyboard covers it (home-indicator inset under the composer)
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(document.documentElement.classList.contains('kb-open')).toBe(true);

    viewport.height = 800;
    textarea.blur();
    document.dispatchEvent(new Event('focusout'));
    await nextFrame();
    expect(document.documentElement.classList.contains('kb-open')).toBe(false);
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

  it('never blocks touchmoves while the viewport is panned (recovery gesture)', async () => {
    // A pan can still happen via exempted targets (drags starting on the
    // textarea bypass the guard for text selection). Once panned, the
    // recovery drag usually starts on empty space - blocking it strands
    // the page in the panned state ("impossible to scroll back down").
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await nextFrame();

    viewport.offsetTop = 120; // viewport currently panned
    const evt = new Event('touchmove', { bubbles: true, cancelable: true });
    document.body.dispatchEvent(evt);
    expect(evt.defaultPrevented).toBe(false);

    viewport.offsetTop = 0; // back to rest - guard active again
    const evt2 = new Event('touchmove', { bubbles: true, cancelable: true });
    document.body.dispatchEvent(evt2);
    expect(evt2.defaultPrevented).toBe(true);
  });

  it('clears a stale inset via the settle poller when close events are missed', async () => {
    // Standalone PWAs resize innerHeight and visualViewport non-atomically
    // and can miss the final close event entirely (keyboard dismissed via
    // its own dismiss key = no blur). A poller active only while inset > 0
    // must clear the stale offset without any event.
    vi.useFakeTimers();
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    expect(getInset()).toBe('300px');
    // Drain pending rAF re-checks (focus handlers) while the keyboard is
    // still open, so only the poller can observe the change below
    await vi.advanceTimersByTimeAsync(50);
    expect(getInset()).toBe('300px');

    // Keyboard silently closes: geometry restored, NO events fire
    viewport.height = 800;
    await vi.advanceTimersByTimeAsync(1000);

    expect(getInset()).toBe('0px');
    vi.useRealTimers();
  });

  it('auto-resets a stale focus pan while the keyboard stays open', async () => {
    // Safari strands the page: iOS re-pans the window AFTER our one-shot
    // keyboard-open scrollTo(0,0), and later updates early-return on
    // "inset unchanged" - the shrunk app sits above a dead band forever.
    // The settle poller must detect scrollY > 0 with the keyboard open
    // and scroll back.
    vi.useFakeTimers();
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(50); // drain the open-transition rAF
    const callsAfterOpen = scrollToSpy.mock.calls.length;

    // iOS re-pans the window after our nudge - no event fires
    Object.defineProperty(window, 'scrollY', { value: 300, configurable: true });
    await vi.advanceTimersByTimeAsync(1000);

    expect(scrollToSpy.mock.calls.length).toBeGreaterThan(callsAfterOpen);
    expect(scrollToSpy).toHaveBeenLastCalledWith(0, 0);
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    scrollToSpy.mockRestore();
    vi.useRealTimers();
  });

  it('resets a stale window scroll even when no inset applies', async () => {
    // With interactive-widget=resizes-content the platform shrinks the
    // layout itself (inset stays 0), but iOS still fires its caret-reveal
    // scroll against the PRE-resize geometry and never re-clamps it. The
    // window is never legitimately scrolled (html/body overflow hidden) -
    // the recovery must not be gated on inset > 0.
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    Object.defineProperty(window, 'scrollY', { value: 291, configurable: true });
    window.dispatchEvent(new Event('scroll'));

    expect(scrollToSpy).toHaveBeenCalledWith(0, 0);
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    scrollToSpy.mockRestore();
  });

  it('never resets the pan while a touch is in progress', async () => {
    // Resetting mid-drag would yank the page out from under the user's
    // finger (the recovery-drag escape hatch exists for the same reason)
    vi.useFakeTimers();
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    textarea.focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(50);
    const callsAfterOpen = scrollToSpy.mock.calls.length;

    document.body.dispatchEvent(new Event('touchstart', { bubbles: true }));
    Object.defineProperty(window, 'scrollY', { value: 300, configurable: true });
    await vi.advanceTimersByTimeAsync(1000);
    expect(scrollToSpy.mock.calls.length).toBe(callsAfterOpen);

    // Touch lifts - the next poll may correct it
    document.body.dispatchEvent(new Event('touchend', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(scrollToSpy.mock.calls.length).toBeGreaterThan(callsAfterOpen);
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    scrollToSpy.mockRestore();
    vi.useRealTimers();
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
