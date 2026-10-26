/**
 * Programmatic scrolls of #messages: tokens that mark our own scrolls so
 * scroll listeners never read them as the user's, the stream-follow marker,
 * and scroll wrappers that hold a token for the scroll's duration.
 */
import { scrollToBottom, scrollToElementTop, scrollToPosition, type SmoothScrollOptions } from './dom';
import { SCROLL_PROGRAMMATIC_RESET_DELAY_MS } from '../config';

// Programmatic scrolls in flight, one token each. Scroll listeners ignore
// scroll events while any is held, so our own scrolls never read as the
// user's. Tokens (not one boolean): overlapping scrolls used to end each
// other's window early - the reserved-space release ended the still-running
// send glide's, and its last frames auto-hid the header.
const programmaticScrollTokens = new Set<number>();
let nextProgrammaticScrollToken = 0;
// A token whose end was never called (a bug elsewhere) must not mute user
// scrolls forever
const PROGRAMMATIC_SCROLL_TOKEN_MAX_MS = 3000;

/**
 * Start a programmatic scroll. Pass the returned token to
 * endProgrammaticScroll when the scroll (animation included) is done.
 */
export function beginProgrammaticScroll(): number {
    const token = ++nextProgrammaticScrollToken;
    programmaticScrollTokens.add(token);
    window.setTimeout(() => programmaticScrollTokens.delete(token), PROGRAMMATIC_SCROLL_TOKEN_MAX_MS);
    return token;
}

/**
 * End a programmatic scroll - after a short delay, so the scroll events it
 * caused (dispatched a frame later) still count as ours.
 */
export function endProgrammaticScroll(token: number): void {
    window.setTimeout(() => programmaticScrollTokens.delete(token), SCROLL_PROGRAMMATIC_RESET_DELAY_MS);
}

/**
 * Whether a programmatic scroll is currently in flight - scroll listeners
 * use this to avoid attributing our own scrolls to the user.
 */
export function isProgrammaticScrollActive(): boolean {
    return programmaticScrollTokens.size > 0;
}

// Where the last stream-follow scroll left #messages (see isStreamFollowScroll)
let lastFollowScrollTop: number | null = null;

/** Record the position a stream-follow scroll just wrote. */
export function markStreamFollowScroll(scrollTop: number): void {
    lastFollowScrollTop = scrollTop;
}

/**
 * Whether the latest scroll event on `container` came from following a
 * stream (pinned to the bottom as tokens arrive). Those follow scrolls are
 * not marked programmatic - a marker window per token would swallow the
 * user's scroll-up that pauses following - so they record their position
 * instead. Scroll events dispatch a frame AFTER the write, and finalize may
 * have shrunk the message meanwhile (the browser clamps to the new bottom),
 * so a clamp below that position to the bottom counts too. Spent on the
 * first event that isn't one, so a later user scroll never matches.
 */
export function isStreamFollowScroll(container: HTMLElement): boolean {
    if (lastFollowScrollTop === null) return false;
    const top = container.scrollTop;
    const atBottom = container.scrollHeight - top - container.clientHeight < 1;
    if (Math.abs(top - lastFollowScrollTop) < 1 || (top < lastFollowScrollTop && atBottom)) {
        return true;
    }
    lastFollowScrollTop = null;
    return false;
}

/**
 * Perform a programmatic scroll to bottom that won't trigger user scroll detection.
 * This is a convenience wrapper that handles the markers automatically.
 * @param element The element to scroll
 * @param smooth Whether to use smooth scrolling
 */
export function programmaticScrollToBottom(element: HTMLElement, smooth = false): void {
    // Already pinned: scrollTo() is a no-op and fires no scroll event, so
    // don't open a "programmatic" window - it would only swallow a genuine
    // user scroll that lands inside it (e.g. the composer hiding on the
    // Storage page re-pinned an empty list right before the user scrolled,
    // and the auto-hide header ignored that scroll).
    if (element.scrollHeight - element.scrollTop - element.clientHeight < 1) {
        return;
    }
    const token = beginProgrammaticScroll();
    // Held until the animation actually ends (finished, aborted or cancelled)
    scrollToBottom(element, smooth, () => endProgrammaticScroll(token));
}

/**
 * Perform a programmatic scroll to element top that won't trigger user scroll detection.
 * This is a convenience wrapper that handles the markers automatically.
 * @param container The scrollable container
 * @param targetElement The element to scroll to (its top will be at the top of the viewport)
 * @param smooth Whether to use smooth scrolling (default: true)
 */
export function programmaticScrollToElementTop(
    container: HTMLElement,
    targetElement: HTMLElement,
    smooth = true
): void {
    const token = beginProgrammaticScroll();
    scrollToElementTop(container, targetElement, smooth, () => endProgrammaticScroll(token));
}

/**
 * Programmatic scroll to an absolute position (see programmaticScrollToElementTop).
 */
export function programmaticScrollToPosition(
    container: HTMLElement,
    targetTop: number,
    smooth = true,
    options: SmoothScrollOptions = {},
    onDone?: () => void
): void {
    const token = beginProgrammaticScroll();
    scrollToPosition(container, targetTop, smooth, () => {
        endProgrammaticScroll(token);
        onDone?.();
    }, options);
}
