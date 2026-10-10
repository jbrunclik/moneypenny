/**
 * Scroll handling once an assistant response has finished rendering
 * (streaming done or batch reply). Anchored (send-to-top) turns stay put;
 * a followed stream stays at the bottom; an unanchored batch reply jumps to
 * the top of a long answer. Never fight a user who scrolled away.
 */

import { RESPONSE_JUMP_MIN_VIEWPORT_RATIO } from '../config';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { getElementById, isScrolledToBottom } from '../utils/dom';
import {
  enableScrollOnImageLoad,
  getThumbnailObserver,
  isProgrammaticScrollActive,
  observeThumbnail,
  programmaticScrollToBottom,
  programmaticScrollToElementTop,
} from '../utils/thumbnails';

/**
 * Watch for a USER scroll between now and a deferred (rAF) scroll of ours.
 * Position deltas can't see the case that bit us: the user scrolls "to the
 * top" of a list that only just became scrollable, landing within a few px
 * of where it already was, and the deferred pin then yanked them back down.
 * A scroll event fires regardless of how far the position moved.
 */
export function watchForUserScroll(container: HTMLElement): () => boolean {
  let scrolled = false;
  let last = container.scrollTop;
  const onScroll = (): void => {
    const cur = container.scrollTop;
    const distanceFromBottom = container.scrollHeight - cur - container.clientHeight;
    // A user scroll-up moves UP and leaves a gap to the bottom. Two things
    // also fire scroll events here and must NOT count: the browser clamping
    // scrollTop when the finalized message is shorter than the streaming
    // placeholder (moves up, but lands exactly at the new bottom), and
    // scroll anchoring when content above grows (moves down).
    if (!isProgrammaticScrollActive() && cur < last - 1 && distanceFromBottom > 1) {
      scrolled = true;
    }
    last = cur;
  };
  container.addEventListener('scroll', onScroll, { passive: true });
  return () => {
    container.removeEventListener('scroll', onScroll);
    return scrolled;
  };
}

/**
 * Handle scroll-to-bottom for lazy-loaded images after message completion.
 */
export function handleImageScrollAfterMessage(
  messageEl: HTMLElement,
  files: Array<{ type: string; previewUrl?: string }> | undefined
): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer || !files) return;

  const hasImagesToLoad = files.some((f) => f.type.startsWith('image/') && !f.previewUrl);
  const wasAtBottom = isScrolledToBottom(messagesContainer);

  if (hasImagesToLoad && wasAtBottom) {
    enableScrollOnImageLoad();
    programmaticScrollToBottom(messagesContainer, false);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        triggerVisibleImageObservation(messageEl, messagesContainer);
        checkScrollButtonVisibility();
      });
    });
  } else {
    if (wasAtBottom) {
      programmaticScrollToBottom(messagesContainer);
    }
    requestAnimationFrame(() => {
      checkScrollButtonVisibility();
    });
  }
}

/**
 * Trigger observation for visible images that haven't started loading.
 */
export function triggerVisibleImageObservation(
  messageEl: HTMLElement,
  container: HTMLElement
): void {
  const images = messageEl.querySelectorAll<HTMLImageElement>(
    'img[data-message-id][data-file-index]:not([src])'
  );
  const containerRect = container.getBoundingClientRect();

  images.forEach((img) => {
    const rect = img.getBoundingClientRect();
    const isVisible = rect.top < containerRect.bottom && rect.bottom > containerRect.top;
    if (isVisible && !img.src) {
      getThumbnailObserver().unobserve(img);
      observeThumbnail(img);
    }
  });
}

/**
 * Only jump to the top of responses taller than the viewport: the jump
 * exists so long answers can be read from the start, but for a short answer
 * that's already fully visible it's a jarring leap away from the bottom the
 * user was just watching.
 */
function isShortResponse(messageEl: HTMLElement, container: HTMLElement): boolean {
  return messageEl.offsetHeight <= container.clientHeight * RESPONSE_JUMP_MIN_VIEWPORT_RATIO;
}

/**
 * A reply finished in an anchored (send-to-top) turn the user didn't
 * re-follow: the view is already on the turn, so nothing moves - only start
 * the images now in view and refresh the scroll button.
 */
export function settleAnchoredReply(messagesContainer: HTMLElement, messageEl: HTMLElement): void {
  requestAnimationFrame(() => {
    triggerVisibleImageObservation(messageEl, messagesContainer);
    checkScrollButtonVisibility();
  });
}

/**
 * A batch reply was just added while the user was at the bottom: scroll to
 * the top of it (batch mode shows the complete message) on the next frame.
 */
export function scrollToBatchReply(
  messagesContainer: HTMLElement,
  messageId: string,
  hasImagesToLoad: boolean
): void {
  // Capture scroll position right after adding the message to detect user scrolling
  // between now and when the RAF fires (race condition on slower engines like WebKit)
  const scrollTopAfterAdd = messagesContainer.scrollTop;
  const userScrolledSinceAdd = watchForUserScroll(messagesContainer);

  // Use RAF to ensure layout is settled after adding message
  requestAnimationFrame(() => {
    // Re-check: if user scrolled away between adding message and this frame,
    // respect their intent rather than hijacking their scroll position
    if (userScrolledSinceAdd() || Math.abs(messagesContainer.scrollTop - scrollTopAfterAdd) > 20) {
      checkScrollButtonVisibility();
      return;
    }

    const messageEl = messagesContainer.querySelector<HTMLElement>(
      `[data-message-id="${messageId}"]`
    );
    if (messageEl) {
      // Short responses that fit the viewport scroll to the bottom
      // instead of jumping to the message top (see the streaming-done
      // path for rationale). Instant, not smooth: the smooth animator
      // has no user-interference abort and would fight a user scroll
      // for its whole 300-600ms run.
      if (isShortResponse(messageEl, messagesContainer)) {
        programmaticScrollToBottom(messagesContainer);
      } else {
        programmaticScrollToElementTop(messagesContainer, messageEl, true);
      }

      // If message has images to load, trigger observation for visible ones
      if (hasImagesToLoad) {
        requestAnimationFrame(() => {
          triggerVisibleImageObservation(messageEl, messagesContainer);
        });
      }
    }
    checkScrollButtonVisibility();
  });
}
