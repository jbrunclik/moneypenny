/**
 * Characterization of core/keyboard-viewport.ts: every write the module
 * makes (style properties, the kb-open class, window scrolls, the caret
 * nudge, pan-guard listeners, anchor holds, bottom pins), with the
 * fake-timer time it happened at, for each branch of the update loop.
 *
 * The iOS keyboard code can only be verified on a real iPhone, so a
 * refactor must leave these recordings byte-identical: same writes, same
 * order, same timing. The [kbN] build marker is normalized out.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const ctl = {
  atAnchor: false,
  anchored: false,
  atBottom: true,
  userScrolled: false,
  gliding: false,
};
const trace: string[] = [];
let t0 = 0;
function rec(entry: string): void {
  trace.push(`${Date.now() - t0} ${entry}`);
}

vi.mock('@/components/messages/turn-anchor', () => ({
  holdTurnAnchor: () => rec('holdTurnAnchor'),
  isAtTurnAnchor: () => ctl.atAnchor,
  isTurnAnchored: () => ctl.anchored,
}));
vi.mock('@/utils/programmatic-scroll', () => ({
  programmaticScrollToBottom: () => rec('programmaticScrollToBottom'),
}));
vi.mock('@/components/ScrollToBottom', () => ({
  checkScrollButtonVisibility: () => rec('checkScrollButtonVisibility'),
}));
vi.mock('@/utils/dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/dom')>()),
  isScrolledToBottom: () => ctl.atBottom,
  isSmoothScrolling: () => ctl.gliding,
  userScrolledSince: () => ctl.userScrolled,
}));

class MockVisualViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

type KeyboardViewport = typeof import('@/core/keyboard-viewport');

describe('keyboard viewport write trace', () => {
  let kv: KeyboardViewport;
  let viewport: MockVisualViewport;
  let textarea: HTMLTextAreaElement;

  beforeEach(async () => {
    vi.useFakeTimers();
    Object.assign(ctl, { atAnchor: false, anchored: false, atBottom: true, userScrolled: false, gliding: false });
    trace.length = 0;
    localStorage.removeItem('kbdebug');
    document.body.innerHTML = '<div id="messages"></div><textarea id="message-input"></textarea>';
    const root = document.documentElement;
    root.style.removeProperty('--keyboard-inset');
    root.style.removeProperty('--app-vh');
    root.classList.remove('kb-open');
    viewport = new MockVisualViewport();
    Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    Object.defineProperty(navigator, 'standalone', { value: undefined, configurable: true });
    textarea = document.getElementById('message-input') as HTMLTextAreaElement;

    const setProperty = root.style.setProperty.bind(root.style);
    vi.spyOn(root.style, 'setProperty').mockImplementation((name, value, priority) => {
      rec(`setProperty ${name}=${value}`);
      setProperty(name, value, priority);
    });
    const toggle = root.classList.toggle.bind(root.classList);
    vi.spyOn(root.classList, 'toggle').mockImplementation((token, force) => {
      rec(`toggle ${token} ${force}`);
      return toggle(token, force);
    });
    vi.spyOn(window, 'scrollTo').mockImplementation((...args: unknown[]) => {
      rec(`window.scrollTo ${JSON.stringify(args)}`);
    });
    vi.spyOn(textarea, 'setSelectionRange').mockImplementation((start, end) => {
      rec(`setSelectionRange ${start},${end}`);
    });
    const add = document.addEventListener.bind(document);
    vi.spyOn(document, 'addEventListener').mockImplementation((type, listener, options) => {
      if (type === 'touchmove') rec(`add touchmove ${JSON.stringify(options)}`);
      add(type, listener, options);
    });
    const remove = document.removeEventListener.bind(document);
    vi.spyOn(document, 'removeEventListener').mockImplementation((type, listener, options) => {
      if (type === 'touchmove') rec('remove touchmove');
      remove(type, listener, options);
    });

    vi.resetModules();
    kv = await import('@/core/keyboard-viewport');
    t0 = Date.now();
  });

  afterEach(() => {
    kv.cleanupKeyboardViewportPinning();
    document.body.dispatchEvent(new Event('touchend', { bubbles: true }));
    vi.restoreAllMocks();
    vi.useRealTimers();
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    Object.defineProperty(navigator, 'standalone', { value: undefined, configurable: true });
  });

  function resize(height: number): void {
    viewport.height = height;
    rec(`-- vv resize ${height}`);
    viewport.dispatchEvent(new Event('resize'));
  }

  async function settle(ms = 1000): Promise<void> {
    await vi.advanceTimersByTimeAsync(ms);
  }

  it('init: first measure, the cold-launch re-measures and lifecycle events', async () => {
    kv.initKeyboardViewportPinning();
    await settle(3500);
    rec('-- pageshow');
    window.dispatchEvent(new Event('pageshow'));
    rec('-- visibilitychange');
    document.dispatchEvent(new Event('visibilitychange'));
    await settle(50);
    Object.defineProperty(window, 'innerHeight', { value: 700, configurable: true });
    rec('-- window resize (rotation)');
    window.dispatchEvent(new Event('resize'));
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "3500 -- pageshow",
        "3500 -- visibilitychange",
        "3550 -- window resize (rotation)",
        "3550 setProperty --app-vh=700px",
      ]
    `);
  });

  it('keyboard opens and closes while following the bottom', async () => {
    kv.initKeyboardViewportPinning();
    textarea.value = 'hello';
    textarea.focus();
    textarea.selectionStart = 3;
    textarea.selectionEnd = 3;
    resize(500);
    await settle();
    resize(540); // accessory bar toggle while open
    await settle();
    resize(800);
    textarea.blur();
    rec('-- focusout');
    document.dispatchEvent(new Event('focusout'));
    await settle();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 3,3",
        "16 programmaticScrollToBottom",
        "16 checkScrollButtonVisibility",
        "150 programmaticScrollToBottom",
        "150 checkScrollButtonVisibility",
        "350 programmaticScrollToBottom",
        "350 checkScrollButtonVisibility",
        "600 programmaticScrollToBottom",
        "600 checkScrollButtonVisibility",
        "1000 -- vv resize 540",
        "1000 setProperty --keyboard-inset=260px",
        "1000 toggle kb-open true",
        "1008 programmaticScrollToBottom",
        "1008 checkScrollButtonVisibility",
        "2000 -- vv resize 800",
        "2000 setProperty --keyboard-inset=0px",
        "2000 toggle kb-open false",
        "2000 remove touchmove",
        "2000 -- focusout",
      ]
    `);
  });

  it('keyboard opens while the reader is up the list', async () => {
    ctl.atBottom = false;
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 0,0",
      ]
    `);
  });

  it('keyboard opens on an anchored turn sitting on its anchor', async () => {
    ctl.atAnchor = true;
    ctl.anchored = true;
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle();
    resize(800);
    textarea.blur();
    document.dispatchEvent(new Event('focusout'));
    await settle();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 holdTurnAnchor",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 0,0",
        "150 holdTurnAnchor",
        "350 holdTurnAnchor",
        "600 holdTurnAnchor",
        "1000 -- vv resize 800",
        "1000 setProperty --keyboard-inset=0px",
        "1000 toggle kb-open false",
        "1000 remove touchmove",
        "1008 holdTurnAnchor",
      ]
    `);
  });

  it('delayed anchor holds yield to a user scroll, a glide, and an un-anchored turn', async () => {
    ctl.atAnchor = true;
    ctl.anchored = true;
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle(200);
    ctl.userScrolled = true; // 350ms hold skipped
    await settle(200);
    ctl.userScrolled = false;
    ctl.gliding = true; // 600ms hold skipped
    await settle(600);
    resize(800);
    textarea.blur();
    document.dispatchEvent(new Event('focusout'));
    await settle(50);
    ctl.gliding = false;
    ctl.anchored = false; // turn released before the holds
    textarea.focus();
    resize(500);
    await settle();
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 holdTurnAnchor",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 0,0",
        "150 holdTurnAnchor",
        "1000 -- vv resize 800",
        "1000 setProperty --keyboard-inset=0px",
        "1000 toggle kb-open false",
        "1000 remove touchmove",
        "1008 holdTurnAnchor",
        "1050 -- vv resize 500",
        "1050 setProperty --keyboard-inset=300px",
        "1050 toggle kb-open true",
        "1050 add touchmove {"passive":false}",
        "1056 holdTurnAnchor",
        "1056 window.scrollTo [0,0]",
        "1056 setSelectionRange 0,0",
        "1056 programmaticScrollToBottom",
        "1056 checkScrollButtonVisibility",
        "1200 programmaticScrollToBottom",
        "1200 checkScrollButtonVisibility",
        "1400 programmaticScrollToBottom",
        "1400 checkScrollButtonVisibility",
        "1650 programmaticScrollToBottom",
        "1650 checkScrollButtonVisibility",
      ]
    `);
  });

  it('standalone adds the accessory pill to the inset', async () => {
    Object.defineProperty(navigator, 'standalone', { value: true, configurable: true });
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle(50);
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=350px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 0,0",
        "16 programmaticScrollToBottom",
        "16 checkScrollButtonVisibility",
      ]
    `);
  });

  it('focus guards: pinch zoom, ambiguous and definite shrinks, focusin re-check', async () => {
    kv.initKeyboardViewportPinning();
    resize(690); // ambiguous, nothing focused
    resize(800);
    resize(500); // definite, nothing focused
    await settle(50);
    resize(800);
    await settle(50);
    viewport.scale = 2;
    textarea.focus();
    resize(400); // pinch zoom
    await settle(50);
    viewport.scale = 1;
    resize(800);
    await settle(50);
    textarea.blur();
    await settle(50);
    resize(680); // ambiguous before focus lands
    textarea.focus();
    rec('-- focusin');
    document.dispatchEvent(new Event('focusin'));
    await settle(50);
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 690",
        "0 -- vv resize 800",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 window.scrollTo [0,0]",
        "16 programmaticScrollToBottom",
        "16 checkScrollButtonVisibility",
        "50 -- vv resize 800",
        "50 setProperty --keyboard-inset=0px",
        "50 toggle kb-open false",
        "50 remove touchmove",
        "100 -- vv resize 400",
        "150 programmaticScrollToBottom",
        "150 checkScrollButtonVisibility",
        "150 -- vv resize 800",
        "250 -- vv resize 680",
        "250 -- focusin",
        "256 setProperty --keyboard-inset=120px",
        "256 toggle kb-open true",
        "256 add touchmove {"passive":false}",
        "272 window.scrollTo [0,0]",
        "272 setSelectionRange 0,0",
        "272 programmaticScrollToBottom",
        "272 checkScrollButtonVisibility",
      ]
    `);
  });

  it('stray window scroll: reset at rest, kept on the open transition and under a finger', async () => {
    kv.initKeyboardViewportPinning();
    textarea.focus();
    Object.defineProperty(window, 'scrollY', { value: 291, configurable: true });
    rec('-- window scroll 291');
    window.dispatchEvent(new Event('scroll'));
    Object.defineProperty(window, 'scrollY', { value: 120, configurable: true });
    resize(500); // open transition: no reset in update, the rAF nudge does it
    await settle(50);
    rec('-- touchstart');
    document.body.dispatchEvent(new Event('touchstart', { bubbles: true }));
    Object.defineProperty(window, 'scrollY', { value: 300, configurable: true });
    await settle(700); // poller runs under the finger
    rec('-- touchend');
    document.body.dispatchEvent(new Event('touchend', { bubbles: true }));
    await settle(400); // poller resets
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    Object.defineProperty(document, 'scrollingElement', { value: { scrollTop: 40 }, configurable: true });
    rec('-- vv scroll');
    viewport.dispatchEvent(new Event('scroll'));
    Object.defineProperty(document, 'scrollingElement', { value: document.documentElement, configurable: true });
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- window scroll 291",
        "0 window.scrollTo [0,0]",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 window.scrollTo [0,0]",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 0,0",
        "16 programmaticScrollToBottom",
        "16 checkScrollButtonVisibility",
        "50 -- touchstart",
        "150 programmaticScrollToBottom",
        "150 checkScrollButtonVisibility",
        "350 programmaticScrollToBottom",
        "350 checkScrollButtonVisibility",
        "600 programmaticScrollToBottom",
        "600 checkScrollButtonVisibility",
        "750 -- touchend",
        "900 window.scrollTo [0,0]",
        "1150 -- vv scroll",
        "1150 window.scrollTo [0,0]",
      ]
    `);
  });

  it('settle poller clears a stale inset without events', async () => {
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle(50);
    viewport.height = 800;
    rec('-- silent close');
    await settle(1000);
    expect(trace).toMatchInlineSnapshot(`
      [
        "0 setProperty --app-vh=800px",
        "0 -- vv resize 500",
        "0 setProperty --keyboard-inset=300px",
        "0 toggle kb-open true",
        "0 add touchmove {"passive":false}",
        "16 window.scrollTo [0,0]",
        "16 setSelectionRange 0,0",
        "16 programmaticScrollToBottom",
        "16 checkScrollButtonVisibility",
        "50 -- silent close",
        "150 setProperty --keyboard-inset=0px",
        "150 toggle kb-open false",
        "150 remove touchmove",
        "150 programmaticScrollToBottom",
        "150 checkScrollButtonVisibility",
        "350 programmaticScrollToBottom",
        "350 checkScrollButtonVisibility",
        "600 programmaticScrollToBottom",
        "600 checkScrollButtonVisibility",
      ]
    `);
  });

  it('pan guard blocks only what nothing can consume', async () => {
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle(50);
    const outcomes: string[] = [];
    const move = (target: EventTarget): void => {
      const evt = new Event('touchmove', { bubbles: true, cancelable: true });
      target.dispatchEvent(evt);
      outcomes.push(String(evt.defaultPrevented));
    };
    move(document.body);
    move(textarea);
    const messages = document.getElementById('messages') as HTMLDivElement;
    messages.style.overflowY = 'auto';
    Object.defineProperty(messages, 'scrollHeight', { value: 2000, configurable: true });
    Object.defineProperty(messages, 'clientHeight', { value: 400, configurable: true });
    move(messages);
    viewport.offsetTop = 120;
    move(document.body);
    viewport.offsetTop = 0;
    const uncancelable = new Event('touchmove', { bubbles: true, cancelable: false });
    document.body.dispatchEvent(uncancelable);
    expect(outcomes).toEqual(['true', 'false', 'false', 'false']);
  });

  it('kbdebug overlay content', async () => {
    localStorage.setItem('kbdebug', '1');
    kv.initKeyboardViewportPinning();
    textarea.focus();
    resize(500);
    await settle(50);
    window.dispatchEvent(new Event('scroll'));
    const overlay = [...document.body.children].find((el) => el instanceof HTMLDivElement && el.style.zIndex === '99999');
    const text = (overlay?.textContent ?? '').replace(/\[kb\d+\]/, '[kbN]');
    localStorage.removeItem('kbdebug');
    expect(text).toMatchInlineSnapshot(`
      "inH=800 vvH=500 vvTop=0 scale=1 active=TEXTAREA
      winY=0 docST=0 bodyH=0 docH=0
      scrH=0 outH=768 scrY=0 saB=0 saT=0 standalone=false [kbN]
      msgST=0 msgSH=0 msgCH=0 distBottom=0 cph= padB=0
      msgBot=0 iaTop=undefined iaBot=undefined pillTop=undefined pillBot=undefined
      reduceTransparency=undefined backdropOk=true hdrBg=?
      update {"shrink":0,"keyboardLikely":false,"inset":0,"currentInset":0,"winY":0,"vvTop":0}
      resize {}
      update {"shrink":300,"keyboardLikely":true,"inset":300,"currentInset":0,"winY":0,"vvTop":0}
      update {"shrink":300,"keyboardLikely":true,"inset":300,"currentInset":300,"winY":0,"vvTop":0}
      winscroll {"winY":0}
      update {"shrink":300,"keyboardLikely":true,"inset":300,"currentInset":300,"winY":0,"vvTop":0}"
    `);
  });

  it('debug toggle: five quick taps on the header', async () => {
    kv.initKeyboardViewportPinning();
    // The overlay instance the fresh keyboard-viewport module logs to
    const { initKbDebugToggle } = await import('@/core/keyboard/debug-overlay');
    initKbDebugToggle();
    const header = document.createElement('div');
    header.className = 'chat-header';
    const title = document.createElement('span');
    title.id = 'current-chat-title';
    header.appendChild(title);
    document.body.appendChild(header);
    for (let i = 0; i < 5; i++) {
      title.dispatchEvent(new Event('touchend', { bubbles: true }));
      title.dispatchEvent(new Event('click', { bubbles: true }));
      await settle(100);
    }
    const on = localStorage.getItem('kbdebug');
    await settle(600); // a click right after a touchend is its synthesized twin
    for (let i = 0; i < 5; i++) {
      title.dispatchEvent(new Event('click', { bubbles: true }));
      await settle(100);
    }
    expect([on, localStorage.getItem('kbdebug')]).toEqual(['1', '0']);
    localStorage.removeItem('kbdebug');
  });
});
