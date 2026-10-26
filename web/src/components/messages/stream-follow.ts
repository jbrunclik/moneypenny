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

  // Debounce timeout is ONLY used for re-enabling auto-scroll (when user scrolls back to bottom)
  // This prevents rapid re-enabling when user is scrolling around near the bottom
  let resumeDebounceTimeout: number | undefined;

  // Handle user scroll interaction (wheel or touch)
  // This immediately pauses auto-scroll since it's definitely user-initiated
  const handleUserScroll = (): void => {
    const current = getStreamingContext();
    if (!current?.shouldAutoScroll) return;

    current.shouldAutoScroll = false;
    log.debug('Streaming auto-scroll paused (user interaction detected)');

    // Show visual indicator on scroll button - once there is answer text
    // (a growing thinking trace isn't "new messages")
    if (current.hasReplyText) setStreamingPausedIndicator(true);

    // Clear any pending resume timeout
    if (resumeDebounceTimeout) {
      clearTimeout(resumeDebounceTimeout);
      resumeDebounceTimeout = undefined;
    }
  };

  // Track scroll position to detect upward user scrolls that produce no
  // wheel/touchmove event (scrollbar drag, PageUp/Home/arrow keys)
  let lastScrollTop = container.scrollTop;

  // Handle scroll events: pause on a real upward scroll while following,
  // re-enable when the user scrolls back to the bottom
  const scrollHandler = (): void => {
    const current = getStreamingContext();
    if (!current) return;

    const scrollTop = container.scrollTop;
    const previousScrollTop = lastScrollTop;
    // Ignore iOS rubber-band out-of-bounds values
    if (scrollTop >= 0) {
      lastScrollTop = scrollTop;
    }

    if (current.shouldAutoScroll) {
      // Direction-based pause, complementing the wheel/touchmove listeners.
      // Content growth and our own follow scrolls only move scrollTop DOWN
      // (or clamp it while staying at the bottom), so an upward move that
      // isn't programmatic and lands away from the bottom is user intent.
      const movedUp = scrollTop >= 0 && previousScrollTop >= 0 && scrollTop < previousScrollTop;
      if (
        movedUp &&
        !isProgrammaticScrollActive() &&
        !isScrolledToBottom(container, STREAMING_SCROLL_THRESHOLD_PX)
      ) {
        handleUserScroll();
      }
      return;
    }

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
      if (resumeDebounceTimeout) {
        clearTimeout(resumeDebounceTimeout);
      }

      resumeDebounceTimeout = window.setTimeout(() => {
        const resumed = getStreamingContext();
        if (!resumed) return;

        // Re-check position after debounce (user might have scrolled away again)
        const stillAtBottom = isScrolledToBottom(container, STREAMING_RESUME_THRESHOLD_PX);
        if (stillAtBottom && !resumed.shouldAutoScroll) {
          resumed.shouldAutoScroll = true;
          log.debug('Streaming auto-scroll resumed (user scrolled to bottom)');

          // Clear the visual indicator
          setStreamingPausedIndicator(false);
        }
        resumeDebounceTimeout = undefined;
      }, STREAMING_SCROLL_RESUME_DEBOUNCE_MS);
    }
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
    const current = getStreamingContext();
    if (!current || current.shouldAutoScroll) return;
    if (resumeDebounceTimeout) {
      clearTimeout(resumeDebounceTimeout);
      resumeDebounceTimeout = undefined;
    }
    current.shouldAutoScroll = true;
    setStreamingPausedIndicator(false);
    log.debug('Streaming auto-scroll resumed (scroll button tapped)');
  });

  // Store cleanup function
  context.scrollListenerCleanup = () => {
    if (resumeDebounceTimeout) {
      clearTimeout(resumeDebounceTimeout);
    }
    container.removeEventListener('wheel', handleUserScroll);
    container.removeEventListener('touchmove', handleUserScroll);
    offMessagesScroll('streaming-autoscroll-resume');
    setOnJumpToBottom(null);
  };
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
