// DOM utility functions

import { SCROLL_BOTTOM_THRESHOLD_PX } from '../config';


// The bottom animation's settle phase: pinned until the height has been
// stable this long, giving up after the max
const SMOOTH_SCROLL_SETTLE_MS = 400;
const SMOOTH_SCROLL_SETTLE_MAX_MS = 1500;
// A touchmove this recent means a finger is on the list (no momentum stop)
const MOMENTUM_STOP_TOUCH_GUARD_MS = 100;
// How long a glide keeps re-writing a target the browser didn't take
const SMOOTH_SCROLL_LAND_MAX_MS = 500;

/**
 * Escape HTML special characters to prevent XSS
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Get element by ID with type assertion
 */
export function getElementById<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

/**
 * Query selector with type assertion
 */
export function querySelector<T extends Element>(
  selector: string,
  parent: ParentNode = document
): T | null {
  return parent.querySelector(selector) as T | null;
}

/**
 * Query selector all with type assertion
 */
export function querySelectorAll<T extends Element>(
  selector: string,
  parent: ParentNode = document
): NodeListOf<T> {
  return parent.querySelectorAll(selector) as NodeListOf<T>;
}

/**
 * Create element with optional attributes and children
 */
export function createElement<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes?: Record<string, string>,
  children?: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);

  if (attributes) {
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, value);
    }
  }

  if (children) {
    for (const child of children) {
      if (typeof child === 'string') {
        element.appendChild(document.createTextNode(child));
      } else {
        element.appendChild(child);
      }
    }
  }

  return element;
}

/**
 * Add event listener with automatic cleanup
 */
export function addEventListenerWithCleanup<K extends keyof HTMLElementEventMap>(
  element: HTMLElement,
  type: K,
  listener: (ev: HTMLElementEventMap[K]) => void,
  options?: boolean | AddEventListenerOptions
): () => void {
  element.addEventListener(type, listener, options);
  return () => element.removeEventListener(type, listener, options);
}

/**
 * Auto-resize textarea to fit content
 */
export function autoResizeTextarea(textarea: HTMLTextAreaElement): void {
  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight}px`;
}

// Track the current smooth scroll animation frame ID for cancellation
let currentSmoothScrollAnimationId: number | null = null;
// Completion callback of the running animation (fires on finish, abort or cancel)
let currentSmoothScrollDone: (() => void) | null = null;

// When the user last touched-moved / wheeled / key-scrolled the list (see
// ScrollToBottom's takeover listeners) - delayed re-pins of ours check it
let lastUserScrollIntentAt = -Infinity;

/** The user just started scrolling the list themselves. */
export function noteUserScrollIntent(): void {
  lastUserScrollIntentAt = performance.now();
}

/** Whether the user scrolled the list themselves since `since` (performance.now). */
export function userScrolledSince(since: number): boolean {
  return lastUserScrollIntentAt > since;
}

// On-device scroll diagnostics (the kbdebug overlay registers itself; dom.ts
// can't import it - keyboard-viewport imports this module)
let scrollDebugSink: ((event: string, data: Record<string, unknown>) => void) | null = null;

/** Route scroll diagnostics to the on-device debug overlay. */
export function setScrollDebugSink(sink: ((event: string, data: Record<string, unknown>) => void) | null): void {
  scrollDebugSink = sink;
}

/** Report a scroll event to the debug overlay, if it is on. */
export function scrollDebug(event: string, data: Record<string, unknown> = {}): void {
  scrollDebugSink?.(event, data);
}

function finishSmoothScroll(): void {
  currentSmoothScrollAnimationId = null;
  const done = currentSmoothScrollDone;
  currentSmoothScrollDone = null;
  done?.();
}

/**
 * Cancel any ongoing smooth scroll animation.
 * Call this when user scrolls or when scroll mode is disabled.
 */
export function cancelSmoothScroll(): void {
  if (currentSmoothScrollAnimationId !== null) {
    cancelAnimationFrame(currentSmoothScrollAnimationId);
    scrollDebug('glide-cancel');
  }
  finishSmoothScroll();
}

/**
 * Stop iOS momentum scrolling on `element`. A coasting list ignores
 * scrollTop writes until it comes to rest; toggling overflow ends the coast.
 * Touch devices only (a classic scrollbar would reflow the list).
 */
export function stopMomentumScroll(element: HTMLElement): void {
  if (!window.matchMedia?.('(pointer: coarse)').matches) return;
  // A finger moving on the list right now: the toggle would end their drag
  if (userScrolledSince(performance.now() - MOMENTUM_STOP_TOUCH_GUARD_MS)) return;
  element.style.overflowY = 'hidden';
  void element.offsetHeight;
  element.style.overflowY = '';
}

/** Options of a smooth scroll. */
export interface SmoothScrollOptions {
  /**
   * The user asked for this very scroll (the scroll button, a send): a coast
   * left over from their earlier flick doesn't stop it (stop the momentum
   * first - stopMomentumScroll). Automatic scrolls (follow, merges, image
   * re-pins) yield to it instead: the user flicked up, they are reading.
   */
  ignoreMomentum?: boolean;
}

// How long after the user's last input an outside move still counts as
// theirs: iOS momentum coasts for a second or more after the finger lifts
const USER_SCROLL_MOMENTUM_MS = 1500;

/**
 * Whether the user scrolled the list themselves just now - within the
 * momentum window, so an iOS coast after their flick still counts. A move
 * with no input in it (a keyboard-close clamp, a reservation released) isn't
 * theirs.
 */
export function userScrolledRecently(): boolean {
  return userScrolledSince(performance.now() - USER_SCROLL_MOMENTUM_MS);
}

/** Whether an outside move during a scroll started at `startTime` is the user's. */
function userTookOver(startTime: number, options: SmoothScrollOptions): boolean {
  return userScrolledSince(options.ignoreMomentum ? startTime : startTime - USER_SCROLL_MOMENTUM_MS);
}

/** Whether one of our smooth scrolls (a glide, the bottom animation) is running. */
export function isSmoothScrolling(): boolean {
  return currentSmoothScrollAnimationId !== null;
}

/** The user asked for less motion: smooth scrolls jump instead. */
export function prefersReducedMotion(): boolean {
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
}

/**
 * Scroll element to bottom
 */
export function scrollToBottom(
  element: HTMLElement,
  smooth = false,
  onDone?: () => void,
  options: SmoothScrollOptions = {}
): void {
  // Cancel any ongoing smooth scroll animation before starting a new scroll
  cancelSmoothScroll();

  if (!smooth) {
    element.scrollTo({
      top: element.scrollHeight,
      behavior: 'auto',
    });
    onDone?.();
    return;
  }
  currentSmoothScrollDone = onDone ?? null;

  // Custom smooth scroll with easing for better animation. Reduced motion:
  // a zero-length curve - the jump - but the settle phase below still runs
  // (it is about landing at the real bottom, not about motion)
  const start = element.scrollTop;
  let target = element.scrollHeight - element.clientHeight;
  let distance = target - start;
  const duration = prefersReducedMotion()
    ? 0
    : Math.min(600, Math.max(300, Math.abs(distance) * 0.5)); // 300-600ms based on distance
  // Already at the bottom: nothing to animate or settle (a settle phase
  // would hold a programmatic token for nothing, muting the user's scroll)
  if (Math.abs(distance) < 1) {
    finishSmoothScroll();
    return;
  }
  const startTime = performance.now();
  scrollDebug('bottom-start', { from: Math.round(start), to: Math.round(target), ch: element.clientHeight });

  // Track the position we last wrote and the content height we saw. A
  // position that moved UP against the animation is the user scrolling up -
  // stop and respect it (without this a scroll-up landing inside the 300-600ms
  // animation was overwritten frame by frame). A downward deviation is NOT
  // treated as the user: application code adjusts scrollTop around these
  // animations (pagination keeping its anchor after appending a page, the
  // scroll-to-bottom button after loading the remaining messages) and
  // aborting on those left the list short of the bottom. When the content
  // height changes (scroll anchoring as content above loads, a page appended
  // below) retarget to the new bottom and keep going.
  let expectedScrollTop = start;
  let lastScrollHeight = element.scrollHeight;
  let lastClientHeight = element.clientHeight;
  // After the curve ends, keep pinning while late content lands (a diagram
  // rendering, the actions row, an image) - stopping at the height seen at
  // the last frame left the list short, the button still showing, and the
  // user tapping again
  let settleSince: number | null = null;
  let lastChangeAt = startTime;

  // Easing function: ease-out-cubic
  const easeOutCubic = (t: number): number => {
    return 1 - Math.pow(1 - t, 3);
  };

  const animate = (currentTime: number): void => {
    // Content or viewport height changed (keyboard, composer): new bottom
    if (element.scrollHeight !== lastScrollHeight || element.clientHeight !== lastClientHeight) {
      // A scroll-up landing in the same frame as a height change is still
      // the user's - don't overwrite it with the retarget
      if (element.scrollTop < expectedScrollTop - 5 && userTookOver(startTime, options)) {
        scrollDebug('bottom-abort-user', { top: Math.round(element.scrollTop), expected: Math.round(expectedScrollTop) });
        finishSmoothScroll();
        return;
      }
      lastScrollHeight = element.scrollHeight;
      lastClientHeight = element.clientHeight;
      target = element.scrollHeight - element.clientHeight;
      distance = target - start;
      expectedScrollTop = element.scrollTop;
      lastChangeAt = currentTime;
    } else if (element.scrollTop < expectedScrollTop - 5 && userTookOver(startTime, options)) {
      // The user scrolled up - respect it and stop animating. An upward
      // drift with no input of theirs is iOS momentum from the flick before
      // the tap (the button is outside the list, so the tap doesn't stop
      // it): aborting on it made the button do nothing
      scrollDebug('bottom-abort-user', { top: Math.round(element.scrollTop), expected: Math.round(expectedScrollTop) });
      finishSmoothScroll();
      return;
    }

    const elapsed = currentTime - startTime;
    const progress = duration === 0 ? 1 : Math.min(elapsed / duration, 1);
    const eased = easeOutCubic(progress);

    const newScrollTop = start + distance * eased;
    element.scrollTop = newScrollTop;
    expectedScrollTop = element.scrollTop;

    if (progress < 1) {
      currentSmoothScrollAnimationId = requestAnimationFrame(animate);
      return;
    }
    // Settle: pinned until the height is stable for a moment (bounded). Any
    // move that isn't ours (a slow scrollbar drag) ends it - in this phase
    // we only ever write the bottom
    if (
      settleSince !== null &&
      Math.abs(element.scrollTop - expectedScrollTop) > 1 &&
      currentTime > lastChangeAt &&
      userTookOver(startTime, options)
    ) {
      finishSmoothScroll();
      return;
    }
    settleSince ??= currentTime;
    const stable = currentTime - lastChangeAt >= SMOOTH_SCROLL_SETTLE_MS;
    if (stable || currentTime - settleSince >= SMOOTH_SCROLL_SETTLE_MAX_MS) {
      scrollDebug('bottom-done', { top: Math.round(element.scrollTop), gap: Math.round(element.scrollHeight - element.scrollTop - element.clientHeight) });
      finishSmoothScroll();
    } else {
      currentSmoothScrollAnimationId = requestAnimationFrame(animate);
    }
  };

  currentSmoothScrollAnimationId = requestAnimationFrame(animate);
}

/**
 * Check if element is scrolled to bottom (within threshold)
 */
export function isScrolledToBottom(
  element: HTMLElement,
  threshold: number = SCROLL_BOTTOM_THRESHOLD_PX
): boolean {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight < threshold
  );
}

/**
 * Scroll container so that the target element's top is at the top of the viewport
 * (below the container's scroll-padding-top).
 * @param container - The scrollable container
 * @param targetElement - The element to scroll to
 * @param smooth - Whether to use smooth scrolling animation (default: true)
 */
export function scrollToElementTop(
  container: HTMLElement,
  targetElement: HTMLElement,
  smooth = true,
  onDone?: () => void
): void {
  // Cancel any ongoing smooth scroll animation before starting a new scroll
  cancelSmoothScroll();

  // Calculate target scroll position using getBoundingClientRect for accuracy.
  // offsetTop can be unreliable if offsetParent isn't the scroll container.
  // Formula: element's current visual position relative to container + current scroll
  const containerRect = container.getBoundingClientRect();
  const targetRect = targetElement.getBoundingClientRect();
  // scroll-padding-top is the container's own top inset - the floating
  // header (mobile) / toolbar (desktop) the list scrolls under. Without it
  // the element's first line landed under that header.
  const topInset = parseFloat(getComputedStyle(container).scrollPaddingTop) || 0;
  const targetTop = targetRect.top - containerRect.top + container.scrollTop - topInset;
  scrollToPosition(container, targetTop, smooth, onDone);
}

/**
 * Scroll container to `targetTop`, smoothly unless reduced motion is on.
 * The animation aborts when anything else moves the position (the user, or
 * other code) so it never fights them.
 */
export function scrollToPosition(
  container: HTMLElement,
  targetTop: number,
  smooth = true,
  onDone?: () => void,
  options: SmoothScrollOptions = {}
): void {
  cancelSmoothScroll();

  if (!smooth || prefersReducedMotion()) {
    container.scrollTo({
      top: targetTop,
      behavior: 'auto',
    });
    onDone?.();
    return;
  }
  currentSmoothScrollDone = onDone ?? null;

  // Custom smooth scroll with easing
  const start = container.scrollTop;
  const distance = targetTop - start;
  const duration = Math.min(600, Math.max(300, Math.abs(distance) * 0.5));
  const startTime = performance.now();
  scrollDebug('glide-start', { from: Math.round(start), to: Math.round(targetTop), ch: container.clientHeight, sh: container.scrollHeight });

  // Track expected scroll position to detect external changes
  let expectedScrollTop = start;

  const easeOutCubic = (t: number): number => {
    return 1 - Math.pow(1 - t, 3);
  };

  const animate = (currentTime: number): void => {
    // Detect if scroll position was changed externally (user scrolled or other code)
    // Allow small tolerance for rounding errors
    // Only the user's own input counts (touch, wheel, keys, a scrollbar
    // press): a move with none is iOS momentum still coasting from a flick
    // before the send, or layout - aborting on it left a send-to-top turn
    // where it was, at the bottom of the screen
    const currentScrollTop = container.scrollTop;
    if (Math.abs(currentScrollTop - expectedScrollTop) > 5 && userTookOver(startTime, options)) {
      // External scroll detected - cancel our animation to respect user's intent
      scrollDebug('glide-abort-outside', {
        top: Math.round(currentScrollTop),
        expected: Math.round(expectedScrollTop),
        user: userTookOver(startTime, options),
        ch: container.clientHeight,
        sh: container.scrollHeight,
      });
      finishSmoothScroll();
      return;
    }

    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = easeOutCubic(progress);

    const newScrollTop = start + distance * eased;
    container.scrollTop = newScrollTop;
    expectedScrollTop = newScrollTop;

    if (progress < 1) {
      currentSmoothScrollAnimationId = requestAnimationFrame(animate);
      return;
    }
    // Landed? iOS drops scrollTop writes for a while (a list still coasting,
    // layout not ready): the curve ended with the list short of its target
    // and the send-to-top turn left at the bottom. Keep writing the target
    // (bounded) until it sticks; a target past the end can't be reached.
    const reachable = Math.min(targetTop, container.scrollHeight - container.clientHeight);
    if (Math.abs(container.scrollTop - reachable) > 1 && elapsed < duration + SMOOTH_SCROLL_LAND_MAX_MS) {
      container.scrollTop = targetTop;
      expectedScrollTop = targetTop;
      currentSmoothScrollAnimationId = requestAnimationFrame(animate);
      return;
    }
    scrollDebug('glide-done', { top: Math.round(container.scrollTop), wanted: Math.round(targetTop) });
    finishSmoothScroll();
  };

  currentSmoothScrollAnimationId = requestAnimationFrame(animate);
}

/**
 * Toggle class on element
 */
export function toggleClass(
  element: HTMLElement,
  className: string,
  force?: boolean
): boolean {
  return element.classList.toggle(className, force);
}

/**
 * Show element (remove hidden class)
 */
export function showElement(element: HTMLElement): void {
  element.classList.remove('hidden');
}

/**
 * Hide element (add hidden class)
 */
export function hideElement(element: HTMLElement): void {
  element.classList.add('hidden');
}

/**
 * Clear all children from an element
 *
 * Preferred over `element.innerHTML = ''` because:
 * - More explicit about intent (clearing content, not setting HTML)
 * - Avoids HTML parsing overhead
 * - Follows the principle of using textContent/DOM methods over innerHTML
 */
export function clearElement(element: HTMLElement): void {
  element.textContent = '';
}