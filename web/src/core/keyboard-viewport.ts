/**
 * Mobile keyboard viewport pinning.
 *
 * The layout is fixed (html/body: 100vh, overflow hidden), so an on-screen
 * keyboard OVERLAYS the page instead of resizing it - the newest messages
 * and the streaming tail can hide behind the keyboard. This module measures
 * the keyboard overlap via visualViewport, exposes it as --keyboard-inset
 * (consumed by base.css to shrink the layout above the keyboard), and
 * re-pins the messages scroll to the bottom when the user was following.
 */
import { getElementById, isScrolledToBottom } from '../utils/dom';
import { programmaticScrollToBottom } from '../utils/thumbnails';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { KEYBOARD_DEFINITE_SHRINK_PX, KEYBOARD_INSET_MIN_PX } from '../config';
import { createLogger } from '../utils/logger';

const log = createLogger('keyboard-viewport');

function isEditableElement(el: Element | null): boolean {
  if (!el) return false;
  return (
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'INPUT' ||
    (el as HTMLElement).isContentEditable
  );
}

/** True when some ancestor of the touch target can actually scroll. */
function touchCanScrollSomewhere(target: EventTarget | null): boolean {
  let el = target instanceof Element ? target : null;
  while (el && el !== document.documentElement) {
    if (el.scrollHeight > el.clientHeight) {
      const overflowY = getComputedStyle(el).overflowY;
      if (overflowY === 'auto' || overflowY === 'scroll') return true;
    }
    el = el.parentElement;
  }
  return false;
}

// With the keyboard open, iOS pans the VISUAL viewport within the still-
// full-height layout viewport - our shrunk page leaves a keyboard-sized
// pan range, so drags on non-scrollable screens (welcome screen) bounce
// the whole page. Prevent touchmoves nothing can consume while the inset
// is active. passive:false is required to be allowed to preventDefault.
const panGuard = (e: TouchEvent | Event): void => {
  if (!e.cancelable) return;
  // Escape hatch: if the viewport is ALREADY panned (a pan can slip in
  // via exempted targets, e.g. drags starting on the textarea), never
  // block - otherwise the recovery drag on empty space is prevented and
  // the page is stranded in the panned state
  if ((window.visualViewport?.offsetTop ?? 0) > 0) return;
  // Never interfere with drags inside form controls (text selection,
  // native textarea scrolling)
  if (e.target instanceof Element && isEditableElement(e.target.closest('textarea, input'))) {
    return;
  }
  if (touchCanScrollSomewhere(e.target)) return;
  e.preventDefault();
};

let panGuardInstalled = false;

function setPanGuard(active: boolean): void {
  if (active === panGuardInstalled) return;
  panGuardInstalled = active;
  if (active) {
    document.addEventListener('touchmove', panGuard, { passive: false });
  } else {
    document.removeEventListener('touchmove', panGuard);
  }
}

// Diagnostic overlay for real-device debugging (?kbdebug=1): the keyboard
// inset has failed on iOS in ways that resist local reproduction - this
// shows every input to the decision so a user screenshot pinpoints it.
let debugEl: HTMLDivElement | null = null;
let debugEventLog: string[] = [];

function kbDebugEnabled(): boolean {
  // ?kbdebug=1 in a browser tab; PWAs launch from a fixed start_url, so
  // the flag also persists via localStorage (toggled by 5 quick taps on
  // the chat title - see initKbDebugToggle)
  return location.search.includes('kbdebug') || localStorage.getItem('kbdebug') === '1';
}

/** 5 quick taps on the chat title toggle the overlay (PWA has no URL bar). */
export function initKbDebugToggle(): void {
  let taps = 0;
  let lastTap = 0;
  let lastTouchTs = 0;
  const onTap = (e: Event): void => {
    if (
      !(e.target instanceof Element) ||
      !e.target.closest('#current-chat-title, .mobile-header, .chat-header')
    ) {
      return;
    }
    const now = Date.now();
    // A touch tap fires touchend AND a synthesized click - count it once
    if (e.type === 'touchend') {
      lastTouchTs = now;
    } else if (now - lastTouchTs < 500) {
      return;
    }
    taps = now - lastTap < 600 ? taps + 1 : 1;
    lastTap = now;
    if (taps >= 5) {
      taps = 0;
      const next = localStorage.getItem('kbdebug') === '1' ? '0' : '1';
      localStorage.setItem('kbdebug', next);
      if (next === '0' && debugEl) {
        debugEl.remove();
        debugEl = null;
      } else {
        kbDebug('enabled', {});
      }
    }
  };
  // touchend, not only click: iOS does NOT deliver document-level click
  // events for taps on non-interactive elements (the same quirk that
  // forbids inline onclick in this codebase)
  document.addEventListener('touchend', onTap);
  document.addEventListener('click', onTap);
}

function kbDebug(event: string, data: Record<string, unknown>): void {
  if (!kbDebugEnabled()) return;
  if (!debugEl) {
    debugEl = document.createElement('div');
    debugEl.style.cssText =
      'position:fixed;top:60px;left:8px;right:8px;z-index:99999;background:rgba(0,0,0,0.85);' +
      'color:#7fff7f;font:11px/1.5 monospace;padding:8px;border-radius:8px;pointer-events:none;' +
      'white-space:pre-wrap;';
    document.body.appendChild(debugEl);
  }
  const vv = window.visualViewport;
  debugEventLog.push(`${event} ${JSON.stringify(data)}`);
  debugEventLog = debugEventLog.slice(-6);
  // Resolved safe-area insets are only readable via a probe element
  let saProbe = document.getElementById('kbdebug-sa-probe');
  if (!saProbe) {
    saProbe = document.createElement('div');
    saProbe.id = 'kbdebug-sa-probe';
    saProbe.style.cssText =
      'position:fixed;visibility:hidden;height:env(safe-area-inset-bottom,0px);' +
      'width:env(safe-area-inset-top,0px);pointer-events:none;';
    document.body.appendChild(saProbe);
  }
  debugEl.textContent =
    `inH=${window.innerHeight} vvH=${vv?.height?.toFixed(0)} vvTop=${vv?.offsetTop?.toFixed(0)} ` +
    `scale=${vv?.scale} active=${document.activeElement?.tagName}\n` +
    `winY=${window.scrollY} docST=${document.scrollingElement?.scrollTop} ` +
    `bodyH=${document.body.clientHeight} docH=${document.documentElement.clientHeight}\n` +
    `scrH=${screen.height} outH=${window.outerHeight} scrY=${window.screenY} ` +
    `saB=${saProbe.offsetHeight} saT=${saProbe.offsetWidth} ` +
    `standalone=${(navigator as Navigator & { standalone?: boolean }).standalone === true} [kb4]\n` +
    debugEventLog.join('\n');
}

// Safety net for missed close events: standalone PWAs resize innerHeight
// and the visualViewport non-atomically, and dismissing the keyboard via
// its own dismiss key fires no blur - if the final event is dropped, the
// inset sticks and the app floats above a dead band. Poll only while the
// keyboard is considered open; the poller re-runs the same update() and
// disarms itself the moment the inset clears.
const SETTLE_POLL_MS = 300;
let settlePoller: ReturnType<typeof setInterval> | null = null;
let settleUpdate: (() => void) | null = null;

function setSettlePoller(active: boolean): void {
  if (active && !settlePoller) {
    settlePoller = setInterval(() => settleUpdate?.(), SETTLE_POLL_MS);
  } else if (!active && settlePoller) {
    clearInterval(settlePoller);
    settlePoller = null;
  }
}

/**
 * The real usable viewport height. Every native measure lies in exactly
 * one environment (observed on device, Aug 2026):
 * - Safari browser: innerHeight is truthful (654 with chrome expanded);
 *   100vh lies (largest viewport, 743).
 * - Standalone PWA (black-translucent): 100vh is truthful (874, the full
 *   webview); innerHeight lies (874 minus the status bar = 812), leaving
 *   a permanent dead band at the bottom when trusted.
 * So: standalone reads a 100vh probe; browsers read innerHeight.
 */
function trueViewportHeight(): number {
  const isStandalone =
    (navigator as Navigator & { standalone?: boolean }).standalone === true ||
    (typeof window.matchMedia === 'function' &&
      window.matchMedia('(display-mode: standalone)').matches);
  if (!isStandalone) return window.innerHeight;
  let probe = document.getElementById('vh-probe');
  if (!probe) {
    probe = document.createElement('div');
    probe.id = 'vh-probe';
    probe.style.cssText =
      'position:fixed;top:0;left:0;width:1px;height:100vh;visibility:hidden;pointer-events:none;';
    document.body.appendChild(probe);
  }
  return probe.offsetHeight || window.innerHeight;
}

/** Resolved env(safe-area-inset-bottom) in px, via a probe element. */
function safeAreaBottom(): number {
  let probe = document.getElementById('sab-probe');
  if (!probe) {
    probe = document.createElement('div');
    probe.id = 'sab-probe';
    probe.style.cssText =
      'position:fixed;visibility:hidden;pointer-events:none;' +
      'height:env(safe-area-inset-bottom,0px);width:1px;';
    document.body.appendChild(probe);
  }
  return probe.offsetHeight;
}

/** Reset module state (tests re-init per case; prod inits once). */
export function cleanupKeyboardViewportPinning(): void {
  setSettlePoller(false);
  setPanGuard(false);
  settleUpdate = null;
}

export function initKeyboardViewportPinning(): void {
  const viewport = window.visualViewport;
  if (!viewport) return; // unsupported browsers keep today's overlay behavior

  let currentInset = 0;

  const update = (): void => {
    // Pinch zoom also shrinks the visual viewport - never treat it as a
    // keyboard. Same for shrinks with no editable element focused
    // (rotations, browser chrome show/hide).
    // The overlap deliberately does NOT include viewport.offsetTop: pan
    // position churns per pixel while the user drags (welcome screen has
    // no inner scroll container, so drags pan the visual viewport), and an
    // offsetTop-dependent inset reflows the whole page mid-gesture - the
    // "extremely laggy scrolling with keyboard open" bug. Keyboard
    // GEOMETRY (innerHeight - height) is stable during pans; the focus-pan
    // that offsetTop used to compensate is reset below via scrollTo(0,0).
    const shrink = Math.max(0, Math.round(window.innerHeight - viewport.height));
    // Editable-focused is the normal signal, but iOS can fire the resize
    // BEFORE focus lands - a shrink this large is unambiguously a keyboard
    // regardless (browser chrome is far smaller), and missing it leaves
    // the composer hidden behind the keyboard
    const keyboardLikely =
      viewport.scale === 1 &&
      (isEditableElement(document.activeElement) || shrink >= KEYBOARD_DEFINITE_SHRINK_PX);
    let overlap = keyboardLikely ? shrink : 0;
    // Standalone: the keyboard also covers the home-indicator zone, which
    // the innerHeight-vs-visualViewport delta does not include (both live
    // in a frame that excludes it) - without adding the safe-area-bottom
    // the composer clips under the keyboard by exactly that strip
    // (observed ~34pt on device). In browsers safe-area-bottom is 0.
    if (overlap > 0) {
      overlap += safeAreaBottom();
    }
    const inset = overlap >= KEYBOARD_INSET_MIN_PX ? overlap : 0;
    kbDebug('update', { shrink, keyboardLikely, inset, currentInset });

    // --app-vh: the layout height CSS cannot know reliably. 100vh is the
    // LARGEST viewport in Safari; 100dvh tracks chrome inconsistently once
    // the keyboard collapses the URL bar, and misbehaves in standalone
    // PWAs. innerHeight is the real layout viewport everywhere AND the
    // measure the inset is computed against - one source of truth. Set
    // BEFORE the inset early-return so rotations/chrome changes that do
    // not move the inset still resize the app.
    const appVh = `${trueViewportHeight()}px`;
    if (document.documentElement.style.getPropertyValue('--app-vh') !== appVh) {
      document.documentElement.style.setProperty('--app-vh', appVh);
    }

    if (inset === currentInset) return;
    const keyboardJustOpened = currentInset === 0 && inset > 0;

    // Capture follow state BEFORE the layout shrinks (afterwards the
    // distance-from-bottom already includes the lost height)
    const container = getElementById<HTMLDivElement>('messages');
    const wasAtBottom = container ? isScrolledToBottom(container) : false;

    currentInset = inset;
    document.documentElement.style.setProperty('--keyboard-inset', `${inset}px`);
    setPanGuard(inset > 0);
    setSettlePoller(inset > 0);
    log.debug('Keyboard inset changed', { inset, wasAtBottom });

    if (inset > 0) {
      requestAnimationFrame(() => {
        // Standalone-PWA caret bug: iOS pans the layout viewport to reveal
        // a focused bottom input BEFORE our height shrink reflows content
        // up - WebKit then draws the caret at the stale pan position,
        // visibly outside the input. Reset the pan (the shrunk layout no
        // longer needs it) and re-assert the selection to force a redraw.
        // Only on the OPEN transition - re-running on later geometry
        // fluctuations would fight in-progress user gestures.
        if (keyboardJustOpened) {
          window.scrollTo(0, 0);
          const active = document.activeElement;
          if (
            active instanceof HTMLTextAreaElement ||
            (active instanceof HTMLInputElement && typeof active.selectionStart === 'number')
          ) {
            const { selectionStart, selectionEnd } = active;
            if (selectionStart !== null && selectionEnd !== null) {
              active.setSelectionRange(selectionStart, selectionEnd);
            }
          }
        }

        if (container && wasAtBottom) {
          // Layout has settled - keep the newest content above the keyboard
          programmaticScrollToBottom(container);
          checkScrollButtonVisibility();
        }
      });
    }
  };

  // The settle poller re-runs this instance's update while the keyboard
  // is considered open (armed inside update via setSettlePoller)
  settleUpdate = update;

  // Initial --app-vh so the first paint already uses the real viewport.
  // Standalone geometry SETTLES LATE on cold launch (even the 100vh probe
  // reads the short value for the first moments, and no event fires while
  // the app sits idle) - re-measure a few times after launch and on
  // lifecycle transitions; update() is change-detected so extra calls are
  // free.
  update();
  for (const delay of [150, 500, 1500, 3000]) {
    setTimeout(update, delay);
  }
  window.addEventListener('pageshow', update);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') requestAnimationFrame(update);
  });
  // Rotation / browser-chrome changes resize the window without
  // necessarily firing visualViewport events in every browser
  window.addEventListener('resize', () => {
    kbDebug('winresize', {});
    update();
  });
  viewport.addEventListener('resize', () => {
    kbDebug('resize', {});
    update();
  });
  // iOS pans the visual viewport when focusing inputs - offsetTop changes
  viewport.addEventListener('scroll', () => {
    kbDebug('vvscroll', {});
    update();
  });
  // Keyboard dismissal doesn't reliably fire a resize on iOS - re-check
  // after focus leaves the input (RAF so activeElement is already updated).
  // Symmetrically re-check on focusin: the resize can precede focus, in
  // which case the resize-time update saw no editable and skipped.
  document.addEventListener('focusout', () => requestAnimationFrame(update));
  document.addEventListener('focusin', () => requestAnimationFrame(update));
}
