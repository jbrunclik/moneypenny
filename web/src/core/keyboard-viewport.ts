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
import { holdTurnAnchor, isAtTurnAnchor, isTurnAnchored } from '../components/messages/turn-anchor';
import { getElementById, isScrolledToBottom, isSmoothScrolling, userScrolledSince } from '../utils/dom';
import { programmaticScrollToBottom } from '../utils/programmatic-scroll';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { createLogger } from '../utils/logger';
import { kbDebug } from './keyboard/debug-overlay';
import { measureKeyboardInset, trueViewportHeight } from './keyboard/metrics';
import { installTouchTracking, isTouchActive, setPanGuard } from './keyboard/touch-guard';

const log = createLogger('keyboard-viewport');

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

// Aborts all listeners of the previous init - re-initializing (tests do,
// prod doesn't) must not leave stale update closures reacting to events
let initAbort: AbortController | null = null;

/** Reset module state (tests re-init per case; prod inits once). */
export function cleanupKeyboardViewportPinning(): void {
  initAbort?.abort();
  initAbort = null;
  setSettlePoller(false);
  setPanGuard(false);
  settleUpdate = null;
  document.documentElement.classList.remove('kb-open');
}

/** Undo iOS's stray window scroll (see update below for when it runs). */
function resetStrayWindowScroll(currentInset: number, inset: number): void {
  // Stale focus-scroll recovery: the window is NEVER legitimately
  // scrolled in this app (html/body are overflow:hidden; all scrolling
  // happens inside #messages) - but iOS scrolls it anyway for its focus
  // caret-reveal, computed against the PRE-resize geometry, and never
  // re-clamps afterwards (device-verified: winY=291 stranded with the
  // keyboard open even under interactive-widget=resizes-content, where
  // the inset correctly stays 0 - so this must NOT be gated on inset).
  // Reset whenever no finger is down; the winscroll listener triggers
  // this update the moment the stray scroll happens.
  if (!isTouchActive() && !(currentInset === 0 && inset > 0)) {
    const scrolled =
      window.scrollY > 0 || (document.scrollingElement?.scrollTop ?? 0) > 0;
    if (scrolled) {
      kbDebug('panreset', { winY: Math.round(window.scrollY) });
      window.scrollTo(0, 0);
    }
  }
}

/** An inset change on a turn sitting on its anchor (see update below). */
function holdAnchorThroughInsetChange(
  container: HTMLDivElement,
  keyboardJustOpened: boolean,
  signal: AbortSignal
): void {
  // Opening or closing: re-fit the reservation, back onto the anchor
  const heldAt = performance.now();
  requestAnimationFrame(() => holdTurnAnchor(container, 'keyboard'));
  if (keyboardJustOpened) {
    for (const delay of [150, 350, 600]) {
      setTimeout(() => {
        // The user scrolling right after focusing owns the position
        // ...and a send glide in flight lands on its own (a hold jumped
        // it to the end, its next frame pulled it back)
        if (!signal.aborted && isTurnAnchored() && !userScrolledSince(heldAt) && !isSmoothScrolling()) {
          holdTurnAnchor(container, 'keyboard-delayed');
        }
      }, delay);
    }
  }
}

/** After an inset change with the keyboard up (see update below). */
function settleWithKeyboardUp(
  container: HTMLDivElement | null,
  wasAtBottom: boolean,
  keyboardJustOpened: boolean,
  signal: AbortSignal
): void {
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

  // The kb-open padding change (setSettlePoller/toggle above) and the
  // composer-height ResizeObserver both reflow the list AFTER the rAF
  // above, growing padding-bottom and un-pinning a bottom-scrolled list -
  // the newest message drifts up, leaving a gap above the composer with
  // the keyboard open. Re-assert the bottom across the settle window (the
  // user won't have scrolled away in the first moments after focusing).
  if (keyboardJustOpened && container && wasAtBottom) {
    for (const delay of [150, 350, 600]) {
      setTimeout(() => {
        if (signal.aborted) return;
        programmaticScrollToBottom(container);
        checkScrollButtonVisibility();
      }, delay);
    }
  }
}

export function initKeyboardViewportPinning(): void {
  const viewport = window.visualViewport;
  if (!viewport) return; // unsupported browsers keep today's overlay behavior
  installTouchTracking();
  initAbort?.abort();
  initAbort = new AbortController();
  const signal = initAbort.signal;

  let currentInset = 0;

  const update = (): void => {
    // Queued rAFs/timeouts can outlive this init (tests re-init; the
    // AbortController removes listeners but cannot cancel callbacks that
    // were already scheduled) - a stale closure must never touch the DOM
    if (signal.aborted) return;
    const { shrink, keyboardLikely, inset } = measureKeyboardInset(viewport);
    kbDebug('update', {
      shrink,
      keyboardLikely,
      inset,
      currentInset,
      winY: Math.round(window.scrollY),
      vvTop: Math.round(viewport.offsetTop),
    });

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

    resetStrayWindowScroll(currentInset, inset);

    if (inset === currentInset) return;
    const keyboardJustOpened = currentInset === 0 && inset > 0;

    // Capture follow state BEFORE the layout shrinks (afterwards the
    // distance-from-bottom already includes the lost height)
    const container = getElementById<HTMLDivElement>('messages');
    // A send-to-top turn sits at its reserved bottom, so "at the bottom" is
    // true for it too - but it must stay anchored, not be pinned (pinning
    // pushed it under the header by the keyboard height)
    const atAnchor = container ? isAtTurnAnchor(container) : false;
    // Anchored but not (yet) on the anchor - a send glide in flight, or the
    // user reading elsewhere in the turn: never bottom-pin (that cancelled the
    // glide and left the turn low); the list's resize observer re-fits it
    const wasAtBottom = container && !isTurnAnchored() ? isScrolledToBottom(container) : false;

    currentInset = inset;
    document.documentElement.style.setProperty('--keyboard-inset', `${inset}px`);
    // CSS hook for space reclaim while the keyboard covers the bottom
    // (e.g. the home-indicator padding under the composer is pointless)
    document.documentElement.classList.toggle('kb-open', inset > 0);
    setPanGuard(inset > 0);
    setSettlePoller(inset > 0);
    log.debug('Keyboard inset changed', { inset, wasAtBottom });

    if (atAnchor && container) {
      holdAnchorThroughInsetChange(container, keyboardJustOpened, signal);
    }

    if (inset > 0) {
      settleWithKeyboardUp(container, wasAtBottom, keyboardJustOpened, signal);
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
  window.addEventListener('pageshow', update, { signal });
  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.visibilityState === 'visible') requestAnimationFrame(update);
    },
    { signal }
  );
  // Rotation / browser-chrome changes resize the window without
  // necessarily firing visualViewport events in every browser
  window.addEventListener(
    'resize',
    () => {
      kbDebug('winresize', {});
      update();
    },
    { signal }
  );
  viewport.addEventListener(
    'resize',
    () => {
      kbDebug('resize', {});
      update();
    },
    { signal }
  );
  // iOS pans the visual viewport when focusing inputs - offsetTop changes
  viewport.addEventListener(
    'scroll',
    () => {
      kbDebug('vvscroll', {});
      update();
    },
    { signal }
  );
  // The focus reveal-pan can also be a WINDOW scroll (Safari, device-
  // verified): without this listener the pan is invisible to update() -
  // the stale-pan recovery never triggers and the debug overlay stays
  // stranded off-screen at its pre-pan position.
  window.addEventListener(
    'scroll',
    () => {
      kbDebug('winscroll', { winY: Math.round(window.scrollY) });
      update();
    },
    { passive: true, signal }
  );
  // Keyboard dismissal doesn't reliably fire a resize on iOS - re-check
  // after focus leaves the input (RAF so activeElement is already updated).
  // Symmetrically re-check on focusin: the resize can precede focus, in
  // which case the resize-time update saw no editable and skipped.
  document.addEventListener('focusout', () => requestAnimationFrame(update), { signal });
  document.addEventListener('focusin', () => requestAnimationFrame(update), { signal });
}
