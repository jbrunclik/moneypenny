/**
 * Scroll handling once an assistant response has finished rendering
 * (streaming done or batch reply): jump to the top of long answers the user
 * was following, stay at the bottom for short ones, and never fight a user
 * who scrolled away in the meantime.
 */

import { RESPONSE_JUMP_MIN_VIEWPORT_RATIO } from '../config';
import { createLogger } from '../utils/logger';
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

const log = createLogger('messaging');

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
 * A finished stream the user was following: scroll to the top of the
 * assistant's response once layout settles (double rAF), unless the user
 * scrolled away while we waited.
 */
export function scrollToFinishedStreamMessage(
  messagesContainer: HTMLElement,
  messageEl: HTMLElement
): void {
  // Record scroll position to detect if user scrolls away before RAF fires
  const scrollTopWhenDone = messagesContainer.scrollTop;
  const userScrolledSinceDone = watchForUserScroll(messagesContainer);

  // Use double RAF to ensure layout is fully settled after finalization
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      // Check if user scrolled away while waiting for RAFs
      const currentScrollTop = messagesContainer.scrollTop;
      const scrolledUp = currentScrollTop < scrollTopWhenDone - 100;
      const nearTop = currentScrollTop < 50;
      if (userScrolledSinceDone() || scrolledUp || nearTop) {
        log.info('Scroll aborted - user scrolled away');
        checkScrollButtonVisibility();
        return;
      }

      // Also check distance from bottom
      const distanceFromBottom =
        messagesContainer.scrollHeight - currentScrollTop - messagesContainer.clientHeight;
      if (distanceFromBottom > 500) {
        log.info('Scroll aborted - user far from bottom');
        checkScrollButtonVisibility();
        return;
      }

      if (isShortResponse(messageEl, messagesContainer)) {
        log.info('Short response - staying at bottom instead of jumping to top');
        programmaticScrollToBottom(messagesContainer);
        checkScrollButtonVisibility();
        return;
      }

      log.info('Scrolling to top of message (programmatic)');
      // Use instant scroll to avoid timing issues with animations
      programmaticScrollToElementTop(messagesContainer, messageEl, false);
      checkScrollButtonVisibility();
    });
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
