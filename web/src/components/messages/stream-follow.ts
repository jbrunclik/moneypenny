/**
 * Following a streaming reply: keep the view pinned to the bottom while the
 * user follows, pause when they scroll away, re-arm when they come back to
 * the bottom or tap the scroll button.
 */
import { getElementById, scrollToBottom, isScrolledToBottom, userScrolledRecently } from '../../utils/dom';
import { onMessagesScroll, offMessagesScroll } from '../../utils/scroll-manager';
import { isProgrammaticScrollActive, markStreamFollowScroll } from '../../utils/programmatic-scroll';
import {
  checkScrollButtonVisibility,
  setOnJumpToBottom,
  setStreamingPausedIndicator,
} from '../ScrollToBottom';
import { createLogger } from '../../utils/logger';
import {
  SCROLL_BUTTON_SHOW_THRESHOLD_PX,
  STREAMING_RESUME_THRESHOLD_PX,
  STREAMING_SCROLL_THRESHOLD_PX,
  STREAMING_SCROLL_RESUME_DEBOUNCE_MS,
} from '../../config';
import { getStreamingContext } from './streaming-context';

const log = createLogger('stream-follow');

/**
 * Set up scroll listeners for streaming that:
 * 1. IMMEDIATELY disables auto-scroll when user interacts (wheel/touch)
 * 2. Re-enables auto-scroll (with debounce) when user scrolls back to bottom
 *
 * We use wheel/touchmove events to detect user interaction instead of scroll
 * direction detection. This is more reliable because:
 * - Image loading can cause scrollTop to change without user interaction
 * - Layout shifts from dynamic content can trigger false "scroll up" detection
 * - wheel/touchmove events ONLY fire on actual user input
 */
export function setupStreamingScrollListener(container: HTMLElement): void {
  const context = getStreamingContext();
  if (!context) return;

  // Clean up any existing listener
  if (context.scrollListenerCleanup) {
    context.scrollListenerCleanup();
  }

  const state: FollowListenerState = {
    container,
    resumeDebounceTimeout: undefined,
    lastScrollTop: container.scrollTop,
  };

  // Handle user scroll interaction (wheel or touch)
  // This immediately pauses auto-scroll since it's definitely user-initiated
  const handleUserScroll = (): void => {
    pauseFollowing(state);
  };

  // Handle scroll events: pause on a real upward scroll while following,
  // re-enable when the user scrolls back to the bottom
  const scrollHandler = (): void => {
    handleFollowScroll(state);
  };

  // Listen for user scroll interactions (wheel/touchmove are interaction
  // events, not scroll - they stay direct)
  container.addEventListener('wheel', handleUserScroll, { passive: true });
  container.addEventListener('touchmove', handleUserScroll, { passive: true });
  // Also listen for scroll events to detect when user scrolls back to bottom
  onMessagesScroll('streaming-autoscroll-resume', scrollHandler);

  // Tapping the scroll-to-bottom button re-arms follow mode synchronously.
  // Leaving it to the position-based resume was fragile: tokens keep growing
  // scrollHeight during the smooth animation, so "bottom" is a moving target
  // and the debounced re-attach could miss.
  setOnJumpToBottom(() => {
    resumeFromScrollButton(state);
  });

  // Store cleanup function
  context.scrollListenerCleanup = () => {
    removeFollowListeners(state, handleUserScroll);
  };
}

/** Undo setupStreamingScrollListener: its timer and every listener it added. */
function removeFollowListeners(state: FollowListenerState, handleUserScroll: () => void): void {
  if (state.resumeDebounceTimeout) {
    clearTimeout(state.resumeDebounceTimeout);
  }
  state.container.removeEventListener('wheel', handleUserScroll);
  state.container.removeEventListener('touchmove', handleUserScroll);
  offMessagesScroll('streaming-autoscroll-resume');
  setOnJumpToBottom(null);
}

/** What one streaming scroll listener remembers between events. */
interface FollowListenerState {
  container: HTMLElement;
  // Debounce timeout is ONLY used for re-enabling auto-scroll (when user scrolls back to bottom)
  // This prevents rapid re-enabling when user is scrolling around near the bottom
  resumeDebounceTimeout: number | undefined;
  // Track scroll position to detect upward user scrolls that produce no
  // wheel/touchmove event (scrollbar drag, PageUp/Home/arrow keys)
  lastScrollTop: number;
}

/** The user took over: stop following the reply. */
function pauseFollowing(state: FollowListenerState): void {
  const current = getStreamingContext();
  if (!current?.shouldAutoScroll) return;

  current.shouldAutoScroll = false;
  log.debug('Streaming auto-scroll paused (user interaction detected)');

  // Show visual indicator on scroll button - once there is answer text
  // (a growing thinking trace isn't "new messages")
  if (current.hasReplyText) setStreamingPausedIndicator(true);

  // Clear any pending resume timeout
  if (state.resumeDebounceTimeout) {
    clearTimeout(state.resumeDebounceTimeout);
    state.resumeDebounceTimeout = undefined;
  }
}

/** One scroll event of #messages while a reply streams. */
function handleFollowScroll(state: FollowListenerState): void {
  const current = getStreamingContext();
  if (!current) return;

  const { container } = state;
  const scrollTop = container.scrollTop;
  const previousScrollTop = state.lastScrollTop;
  // Ignore iOS rubber-band out-of-bounds values
  if (scrollTop >= 0) {
    state.lastScrollTop = scrollTop;
  }

  if (current.shouldAutoScroll) {
    pauseIfUserScrolledUp(state, scrollTop, previousScrollTop);
    return;
  }
  resumeIfUserReachedBottom(state, scrollTop, previousScrollTop);
}

/** While following: an upward move away from the bottom that isn't ours pauses. */
function pauseIfUserScrolledUp(state: FollowListenerState, scrollTop: number, previousScrollTop: number): void {
  // Direction-based pause, complementing the wheel/touchmove listeners.
  // Content growth and our own follow scrolls only move scrollTop DOWN
  // (or clamp it while staying at the bottom), so an upward move that
  // isn't programmatic and lands away from the bottom is user intent.
  const movedUp = scrollTop >= 0 && previousScrollTop >= 0 && scrollTop < previousScrollTop;
  if (
    movedUp &&
    !isProgrammaticScrollActive() &&
    !isScrolledToBottom(state.container, STREAMING_SCROLL_THRESHOLD_PX)
  ) {
    pauseFollowing(state);
  }
}

/** While paused: the user scrolling down to the real bottom re-arms (debounced). */
function resumeIfUserReachedBottom(state: FollowListenerState, scrollTop: number, previousScrollTop: number): void {
  const { container } = state;
  // Re-arm following only when the USER scrolls DOWN to the real bottom:
  // our own scrolls (the send-to-top glide ends at the reserved bottom), a
  // small scroll near it, and iOS's rubber-band bounce there (overscrolled
  // positions, then a move back up) must not start chasing the reply
  const atBottom = isScrolledToBottom(container, STREAMING_RESUME_THRESHOLD_PX);
  const maxScrollTop = container.scrollHeight - container.clientHeight;
  const movedDown = scrollTop > previousScrollTop && scrollTop <= maxScrollTop + 1;

  // ...and only the user: a move with no input of theirs (layout, a
  // re-fit, a clamp next to the anchor - an anchored short reply sits
  // within the threshold of the bottom) re-armed chasing the reply
  if (atBottom && movedDown && !isProgrammaticScrollActive() && userScrolledRecently()) {
    // User scrolled back to bottom - use debounce to re-enable auto-scroll
    // This prevents rapid toggling when user is scrolling around near the bottom
    if (state.resumeDebounceTimeout) {
      clearTimeout(state.resumeDebounceTimeout);
    }

    state.resumeDebounceTimeout = window.setTimeout(() => {
      resumeIfStillAtBottom(state);
    }, STREAMING_SCROLL_RESUME_DEBOUNCE_MS);
  }
}

/** The re-arm debounce elapsed: follow again if the user stayed at the bottom. */
function resumeIfStillAtBottom(state: FollowListenerState): void {
  const resumed = getStreamingContext();
  if (!resumed) return;

  // Re-check position after debounce (user might have scrolled away again)
  const stillAtBottom = isScrolledToBottom(state.container, STREAMING_RESUME_THRESHOLD_PX);
  if (stillAtBottom && !resumed.shouldAutoScroll) {
    resumed.shouldAutoScroll = true;
    log.debug('Streaming auto-scroll resumed (user scrolled to bottom)');

    // Clear the visual indicator
    setStreamingPausedIndicator(false);
  }
  state.resumeDebounceTimeout = undefined;
}

/** The scroll button was tapped: follow again right away. */
function resumeFromScrollButton(state: FollowListenerState): void {
  const current = getStreamingContext();
  if (!current || current.shouldAutoScroll) return;
  if (state.resumeDebounceTimeout) {
    clearTimeout(state.resumeDebounceTimeout);
    state.resumeDebounceTimeout = undefined;
  }
  current.shouldAutoScroll = true;
  setStreamingPausedIndicator(false);
  log.debug('Streaming auto-scroll resumed (scroll button tapped)');
}

/**
 * Auto-scroll to keep the thinking indicator visible during streaming.
 * Only scrolls if auto-scroll is enabled (controlled by the scroll listener).
 *
 * Note: We CANNOT check isScrolledToBottom() here because when new content is added,
 * scrollHeight increases, making the user appear "not at bottom" even though they
 * never scrolled. The scroll listener handles detecting actual user scrolls via
 * wheel/touchmove events which only fire on real user input.
 */
export function autoScrollForStreaming(): void {
  const context = getStreamingContext();
  if (!context) return;

  const messagesContainer = getElementById('messages');
  if (!messagesContainer) return;

  if (!context.shouldAutoScroll) {
    // Not following: once the ANSWER runs past the screen, the scroll button
    // pulses - more of this reply is below (see hasReplyText)
    if (
      context.hasReplyText &&
      !isScrolledToBottom(messagesContainer, SCROLL_BUTTON_SHOW_THRESHOLD_PX)
    ) {
      setStreamingPausedIndicator(true);
      checkScrollButtonVisibility();
    }
    return;
  }

  scrollToBottom(messagesContainer);
  markStreamFollowScroll(messagesContainer.scrollTop);
}
