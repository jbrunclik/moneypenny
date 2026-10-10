/**
 * Send-to-top: a new turn scrolls up so the user's message sits just under
 * the header with the reply growing below it (ChatGPT / Claude.ai). The view
 * no longer chases the reply - it is read from its start, and the
 * "New messages" pill offers the rest. A reply shorter than the screen still
 * needs room below it for the message to reach the top, so the reply element
 * reserves it with a min-height until the next turn takes over.
 */

import { TURN_REPLY_MIN_VISIBLE_PX, TURN_SPACE_RELEASE_MS } from '../../config';
import { prefersReducedMotion } from '../../utils/dom';
import {
  isProgrammaticScrollActive,
  markProgrammaticScrollEnd,
  markProgrammaticScrollStart,
  programmaticScrollToPosition,
} from '../../utils/thumbnails';

// Content-coordinate top of the visible area the current turn is anchored
// to (scroll-padding included), or null when no turn is anchored
let anchorTop: number | null = null;

const RESERVED_ATTR = 'data-turn-space';
// While a turn is anchored the list doesn't bottom-align a short chat
// (layout.css): the reservation fills the screen anyway, and the transient
// margin-top:auto collapsing/expanding as the placeholder is swapped moved
// every measurement by its height
const ANCHORED_CLASS = 'turn-anchored';

function topInset(container: HTMLElement): number {
  return parseFloat(getComputedStyle(container).scrollPaddingTop) || 0;
}

/** Height of the band between the header and the composer. */
function visibleHeight(container: HTMLElement): number {
  const bottomInset = parseFloat(getComputedStyle(container).paddingBottom) || 0;
  return container.clientHeight - topInset(container) - bottomInset;
}

/**
 * The element's top in the list's scroll coordinates. Layout position, not
 * getBoundingClientRect: a message's entrance animation transforms it, and
 * measuring mid-animation put the target (and the reservation) tens of px off.
 */
function contentTop(container: HTMLElement, el: HTMLElement): number {
  if (el.offsetParent === container) return el.offsetTop;
  return el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
}

/** Drop the previous turn's reserved space. */
function releaseTurnSpace(container: HTMLElement): void {
  container.querySelectorAll<HTMLElement>(`[${RESERVED_ATTR}]`).forEach((el) => {
    el.style.minHeight = '';
    el.removeAttribute(RESERVED_ATTR);
  });
  container.classList.remove(ANCHORED_CLASS);
  anchorTop = null;
}

/**
 * Reserve room under the anchored turn on `replyEl` (the streaming bubble,
 * the batch loader, or the reply that replaced it) so the turn stays at the
 * top. Call it in the same task that swaps a placeholder for the reply,
 * before anything reads layout, or the browser clamps the position first.
 */
export function reserveTurnSpace(container: HTMLElement, replyEl: HTMLElement): void {
  if (anchorTop === null) return;
  const minHeight = anchorTop + visibleHeight(container) - contentTop(container, replyEl);
  if (minHeight <= 0) {
    replyEl.style.minHeight = '';
    replyEl.removeAttribute(RESERVED_ATTR);
    return;
  }
  replyEl.style.minHeight = `${Math.ceil(minHeight)}px`;
  replyEl.setAttribute(RESERVED_ATTR, '');
}

/**
 * Re-fit the reservation after the band between header and composer changed
 * height (the composer grew/shrank: quick actions, multi-line input, the
 * keyboard) so the list still ends exactly at the anchor - pinning to the
 * bottom instead pushed the turn under the header. Overwrites in place (the
 * element's own top doesn't depend on its min-height), never clearing first:
 * a layout read in between would clamp the position.
 */
export function refreshTurnSpace(container: HTMLElement): void {
  if (anchorTop === null) return;
  container.querySelectorAll<HTMLElement>(`[${RESERVED_ATTR}]`).forEach((el) => {
    reserveTurnSpace(container, el);
  });
}

/** Whether a turn is anchored (send-to-top owns the scroll position). */
export function isTurnAnchored(): boolean {
  return anchorTop !== null;
}

/**
 * Scroll a new turn to the top: `turnEl` (the user's message, or the reply
 * itself for Continue) under the header, `replyEl` below it.
 */
export function anchorTurn(container: HTMLElement, turnEl: HTMLElement, replyEl: HTMLElement): void {
  releaseTurnSpace(container);
  container.classList.add(ANCHORED_CLASS);
  const visible = visibleHeight(container);
  // A message taller than the screen keeps the start of the reply in view
  const measureTarget = (): number =>
    Math.max(
      contentTop(container, turnEl),
      contentTop(container, replyEl) + TURN_REPLY_MIN_VISIBLE_PX - visible
    );
  anchorTop = measureTarget();
  reserveTurnSpace(container, replyEl);
  programmaticScrollToPosition(container, anchorTop - topInset(container), true);
}

/**
 * The reply finished: give the reserved space back. A short answer then
 * settles above the composer (the list's position clamps as the space
 * shrinks - animated, and marked programmatic so the header auto-hide and
 * follow logic don't read it as the user); a long one is taller than its
 * reservation, so nothing moves.
 */
export function settleTurnSpace(container: HTMLElement): void {
  if (anchorTop === null) return;
  anchorTop = null;
  const reserved = [...container.querySelectorAll<HTMLElement>(`[${RESERVED_ATTR}]`)];
  // Still at least screen-tall while the space is held, so the
  // bottom-aligning margin comes back without a jump as it shrinks
  container.classList.remove(ANCHORED_CLASS);
  if (reserved.length === 0) return;

  const clear = (el: HTMLElement): void => {
    el.style.transition = '';
    el.style.minHeight = '';
  };
  if (prefersReducedMotion()) {
    reserved.forEach((el) => {
      el.removeAttribute(RESERVED_ATTR);
      clear(el);
    });
    return;
  }

  // The marker is one global flag: only take it if no other programmatic
  // scroll holds it - ending it under the still-running send glide let the
  // glide's last frames read as the user scrolling (auto-hiding the header)
  const ownsMarker = !isProgrammaticScrollActive();
  if (ownsMarker) markProgrammaticScrollStart();
  for (const el of reserved) {
    el.removeAttribute(RESERVED_ATTR);
    el.style.transition = `min-height ${TURN_SPACE_RELEASE_MS}ms ease-out`;
    void el.offsetHeight; // start from the current height
    el.style.minHeight = '0px';
  }
  window.setTimeout(() => {
    // A new turn may have reserved one of them again meanwhile
    reserved.filter((el) => !el.hasAttribute(RESERVED_ATTR)).forEach(clear);
    if (ownsMarker) markProgrammaticScrollEnd();
  }, TURN_SPACE_RELEASE_MS + 50);
}

/** Forget the anchor (conversation switch re-renders the list). */
export function resetTurnAnchor(container: HTMLElement): void {
  container.classList.remove(ANCHORED_CLASS);
  anchorTop = null;
}
