/**
 * Send-to-top: a new turn scrolls up so the user's message sits just under
 * the header with the reply growing below it (ChatGPT / Claude.ai). The view
 * no longer chases the reply - it is read from its start, and the
 * "New messages" pill offers the rest. A reply shorter than the screen still
 * needs room below it for the message to reach the top, so the reply element
 * reserves it with a min-height until the next turn takes over.
 */

import { TURN_REPLY_MIN_VISIBLE_PX, TURN_SPACE_RELEASE_MS } from '../../config';
import { prefersReducedMotion, scrollDebug } from '../../utils/dom';
import { useStore } from '../../state/store';
import { hasTrackedRequestFor } from '../../core/active-requests';
import {
  beginProgrammaticScroll,
  disableScrollOnImageLoad,
  endProgrammaticScroll,
  programmaticScrollToPosition,
} from '../../utils/thumbnails';

// The anchored turn: its element, and how far below that element's top the
// visible area starts (0, or more for a message taller than the screen).
// Relative to the element, not an absolute coordinate - content inserted
// above it (an interject, an older page, a compaction divider) shifted a
// stored coordinate and left the reservation the wrong size.
let anchor: { el: HTMLElement; extra: number } | null = null;

const RESERVED_ATTR = 'data-turn-space';
// While a turn is anchored the list doesn't bottom-align a short chat
// (layout.css): the reservation fills the screen anyway, and the transient
// margin-top:auto collapsing/expanding as the placeholder is swapped moved
// every measurement by its height
const ANCHORED_CLASS = 'turn-anchored';

function topInset(container: HTMLElement): number {
  return parseFloat(getComputedStyle(container).scrollPaddingTop) || 0;
}

/**
 * The list's bottom clearance for the floating composer: the ::after spacer
 * plus the list gap before it (plus any padding-bottom).
 */
function bottomInset(container: HTMLElement): number {
  const style = getComputedStyle(container);
  const spacer = parseFloat(getComputedStyle(container, '::after').height) || 0;
  const gap = spacer > 0 ? parseFloat(style.rowGap) || 0 : 0;
  return spacer + gap + (parseFloat(style.paddingBottom) || 0);
}

/** Height of the band between the header and the composer. */
function visibleHeight(container: HTMLElement): number {
  return container.clientHeight - topInset(container) - bottomInset(container);
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

/** Content-coordinate top of the visible area the turn is anchored to. */
function anchorTopOf(container: HTMLElement): number | null {
  if (!anchor || !anchor.el.isConnected) return null;
  return contentTop(container, anchor.el) + anchor.extra;
}

/** Drop the previous turn's reserved space. */
function releaseTurnSpace(container: HTMLElement): void {
  container.querySelectorAll<HTMLElement>(`[${RESERVED_ATTR}]`).forEach((el) => {
    el.style.minHeight = '';
    el.removeAttribute(RESERVED_ATTR);
  });
  container.classList.remove(ANCHORED_CLASS);
  anchor = null;
}

/**
 * Reserve room under the anchored turn on `replyEl` (the streaming bubble,
 * the batch loader, or the reply that replaced it) so the turn stays at the
 * top. Call it in the same task that swaps a placeholder for the reply,
 * before anything reads layout, or the browser clamps the position first.
 */
export function reserveTurnSpace(container: HTMLElement, replyEl: HTMLElement): void {
  const anchorTop = anchorTopOf(container);
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
  if (anchor === null) return;
  scrollDebug('anchor-refit', { top: Math.round(container.scrollTop), ch: container.clientHeight });
  container.querySelectorAll<HTMLElement>(`[${RESERVED_ATTR}]`).forEach((el) => {
    reserveTurnSpace(container, el);
  });
}

/** Whether a turn is anchored (send-to-top owns the scroll position). */
export function isTurnAnchored(): boolean {
  // A view that cleared #messages itself (agents, planner, data, programs)
  // took the anchored turn with it - nothing to hold
  return anchor !== null && anchor.el.isConnected;
}

/** Whether the view still sits exactly at the anchored position. */
export function isAtTurnAnchor(container: HTMLElement): boolean {
  const anchorTop = anchorTopOf(container);
  return anchorTop !== null && Math.abs(container.scrollTop - (anchorTop - topInset(container))) < 3;
}

/**
 * Keep an anchored view anchored through a change of the band between header
 * and composer (iOS keyboard opening/closing, composer resize): re-fit the
 * reservation, then put the view back on the anchor. Pinning to the bottom
 * instead pushed the turn under the header by the keyboard's height, and a
 * keyboard closing let the browser clamp it down. Only call it when the view
 * was at the anchor (isAtTurnAnchor) before the change.
 */
export function holdTurnAnchor(container: HTMLElement): void {
  if (anchor === null) return;
  refreshTurnSpace(container);
  const anchorTop = anchorTopOf(container);
  if (anchorTop === null) return;
  const token = beginProgrammaticScroll();
  scrollDebug('anchor-hold', { from: Math.round(container.scrollTop), to: Math.round(anchorTop - topInset(container)) });
  container.scrollTop = anchorTop - topInset(container);
  endProgrammaticScroll(token);
}

/**
 * Scroll a new turn to the top: `turnEl` (the user's message, or the reply
 * itself for Continue) under the header, `replyEl` below it.
 */
export function anchorTurn(container: HTMLElement, turnEl: HTMLElement, replyEl: HTMLElement): void {
  releasing?.();
  releaseTurnSpace(container);
  // The open's "scroll to the bottom as images load" mode would chase the
  // anchored reply to its end once a thumbnail in it loads
  disableScrollOnImageLoad();
  container.classList.add(ANCHORED_CLASS);
  const visible = visibleHeight(container);
  // A message taller than the screen keeps the start of the reply in view
  const measureTarget = (): number =>
    Math.max(
      contentTop(container, turnEl),
      contentTop(container, replyEl) + TURN_REPLY_MIN_VISIBLE_PX - visible
    );
  const target = measureTarget();
  anchor = { el: turnEl, extra: Math.max(0, target - contentTop(container, turnEl)) };
  reserveTurnSpace(container, replyEl);
  programmaticScrollToPosition(container, target - topInset(container), true);
}

/**
 * The reply finished: give the reserved space back. A short answer then
 * settles above the composer (the list's position clamps as the space
 * shrinks - animated, and marked programmatic so the header auto-hide and
 * follow logic don't read it as the user); a long one is taller than its
 * reservation, so nothing moves.
 */
export function settleTurnSpace(container: HTMLElement): void {
  if (anchor === null) return;
  anchor = null;
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

  const token = beginProgrammaticScroll();
  for (const el of reserved) {
    el.removeAttribute(RESERVED_ATTR);
    el.style.transition = `min-height ${TURN_SPACE_RELEASE_MS}ms ease-out`;
    void el.offsetHeight; // start from the current height
    el.style.minHeight = '0px';
  }
  const finish = (): void => {
    window.clearTimeout(timer);
    releasing = null;
    // A new turn may have reserved one of them again meanwhile
    reserved.filter((el) => !el.hasAttribute(RESERVED_ATTR)).forEach(clear);
    endProgrammaticScroll(token);
  };
  const timer = window.setTimeout(finish, TURN_SPACE_RELEASE_MS + 50);
  releasing = finish;
}

// The release animation in flight (settleTurnSpace), finished early when a
// new turn anchors: measuring against a still-shrinking reply put the new
// turn's glide target off by the remaining shrink
let releasing: (() => void) | null = null;

/**
 * A turn of `convId` ended in any way (done, stop, error, recovery, a
 * resumed batch giving up): give back its reserved space if that
 * conversation is on screen. Only a normal done used to - a stopped or
 * failed turn left the empty area and the bottom-align switched off.
 */
export function settleTurnFor(convId: string): void {
  if (useStore.getState().currentConversation?.id !== convId) return;
  // A newer turn started meanwhile (a follow-up while this one's cleanup
  // still ran): the anchor is its now
  if (hasTrackedRequestFor(convId)) return;
  const container = document.getElementById('messages');
  if (container) settleTurnSpace(container);
}

/** Forget the anchor (conversation switch re-renders the list). */
export function resetTurnAnchor(container: HTMLElement): void {
  container.classList.remove(ANCHORED_CLASS);
  anchor = null;
}
