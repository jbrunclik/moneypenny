/**
 * Send-to-top: a new turn scrolls up so the user's message sits just under
 * the header with the reply growing below it (ChatGPT / Claude.ai). The view
 * no longer chases the reply - it is read from its start, and the
 * "New messages" pill offers the rest. A reply shorter than the screen still
 * needs room below it for the message to reach the top, so the reply element
 * reserves it with a min-height until the next turn takes over.
 */

import { TURN_REPLY_MIN_VISIBLE_PX, TURN_SPACE_RELEASE_MS } from '../../config';
import { isSmoothScrolling, prefersReducedMotion, scrollDebug, stopMomentumScroll } from '../../utils/dom';
import { onMessagesScroll } from '../../utils/scroll-manager';
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
let anchor: { el: HTMLElement; replyEl: HTMLElement; extra: number } | null = null;

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

/**
 * How far below the turn's top the anchored view starts: 0, or more when the
 * message is taller than the visible band (the start of the reply stays in
 * view). Depends on the band's height - recomputed when the list resizes
 * (sent with the iOS keyboard open, it closes: the band grows and the turn
 * belongs at the top again, not the keyboard-open offset under the header).
 */
function anchorExtra(container: HTMLElement, turnEl: HTMLElement, replyEl: HTMLElement): number {
  const turnTop = contentTop(container, turnEl);
  const replyStart = contentTop(container, replyEl) + TURN_REPLY_MIN_VISIBLE_PX - visibleHeight(container);
  return Math.max(0, Math.max(turnTop, replyStart) - turnTop);
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
  anchor = { el: turnEl, replyEl, extra: anchorExtra(container, turnEl, replyEl) };
  reserveTurnSpace(container, replyEl);
  // A list still coasting from a flick ignores our writes until it rests
  stopMomentumScroll(container);
  glideToAnchor(container);
}

// Whether the smooth scroll running is the send glide (a resize retargets
// it); the generation tells a retarget's cancelled predecessor apart
let isAnchorGlide = false;
let glideGeneration = 0;

/** Glide the view onto the anchor (the send, or a retarget mid-glide). */
function glideToAnchor(container: HTMLElement): void {
  const anchorTop = anchorTopOf(container);
  if (anchorTop === null) return;
  const generation = ++glideGeneration;
  isAnchorGlide = true;
  programmaticScrollToPosition(container, anchorTop - topInset(container), true, { ignoreMomentum: true }, () => {
    if (generation === glideGeneration) isAnchorGlide = false;
  });
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

/**
 * Keep an anchored turn anchored whenever the list itself changes height -
 * whatever the cause (the iOS keyboard opening or closing, the viewport,
 * the composer). The reservation is sized for the visible band: a taller
 * list made the anchor unreachable (the browser clamped the position down
 * and a glide in flight landed short - device log Oct 10 2026, keyboard
 * closed mid-glide). The keyboard and composer handlers only covered their
 * own changes. Re-fit the reservation; a view that sat on the anchor goes
 * back onto it; a glide in flight lands on its own.
 */
export function initTurnAnchorResizeHold(container: HTMLElement): void {
  if (typeof ResizeObserver !== 'function') return;
  let lastClientHeight = container.clientHeight;
  // The position before a resize: a resize's own clamp fires a scroll event
  // (before the observer runs) that must not count as where the view sat
  let settledTop = container.scrollTop;
  onMessagesScroll('turn-anchor-settled', () => {
    if (container.clientHeight === lastClientHeight) settledTop = container.scrollTop;
  });
  new ResizeObserver(() => {
    const height = container.clientHeight;
    if (height === lastClientHeight) return;
    lastClientHeight = height;
    const anchorTop = anchorTopOf(container);
    if (anchor !== null && anchorTop !== null) {
      const wasAtAnchor = Math.abs(settledTop - (anchorTop - topInset(container))) < 3;
      const gliding = isSmoothScrolling();
      if (anchor.replyEl.isConnected) anchor.extra = anchorExtra(container, anchor.el, anchor.replyEl);
      scrollDebug('anchor-resize', { ch: height, wasAtAnchor, gliding, extra: Math.round(anchor.extra) });
      if (gliding && isAnchorGlide) {
        // Retarget the send glide in flight onto the re-measured anchor
        refreshTurnSpace(container);
        glideToAnchor(container);
      } else if (wasAtAnchor && !gliding) {
        holdTurnAnchor(container);
      } else {
        refreshTurnSpace(container);
      }
    }
    settledTop = container.scrollTop;
  }).observe(container);
}

/** Forget the anchor (conversation switch re-renders the list). */
export function resetTurnAnchor(container: HTMLElement): void {
  container.classList.remove(ANCHORED_CLASS);
  anchor = null;
}
