import { getElementById, isScrolledToBottom, scrollToBottom } from '../utils/dom';
import { CHEVRON_DOWN_ICON } from '../utils/icons';
import { SCROLL_BUTTON_SHOW_THRESHOLD_PX } from '../config';

let scrollButton: HTMLButtonElement | null = null;

// Track whether streaming is active and auto-scroll is paused
let isStreamingPaused = false;

/**
 * Initialize the scroll-to-bottom button
 * Creates the button and sets up scroll listeners on the messages container
 */
export function initScrollToBottom(): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;

  // Create scroll-to-bottom button
  scrollButton = document.createElement('button');
  scrollButton.className = 'scroll-to-bottom hidden';
  scrollButton.setAttribute('aria-label', 'Scroll to bottom');
  scrollButton.innerHTML = CHEVRON_DOWN_ICON;

  // Insert button after messages container (inside .main)
  messagesContainer.parentElement?.insertBefore(
    scrollButton,
    messagesContainer.nextSibling
  );

  // Click handler
  scrollButton.addEventListener('click', () => {
    scrollToBottom(messagesContainer, true);
  });

  // Scroll listener with debounce for performance
  let scrollTimeout: number | undefined;
  messagesContainer.addEventListener('scroll', () => {
    if (scrollTimeout) {
      cancelAnimationFrame(scrollTimeout);
    }
    scrollTimeout = requestAnimationFrame(() => {
      updateScrollButtonVisibility(messagesContainer);
    });
  });
}

/**
 * Update the visibility of the scroll-to-bottom button
 * Shows the button when user has scrolled up, hides when at bottom
 */
function updateScrollButtonVisibility(container: HTMLElement): void {
  if (!scrollButton) return;

  // Use a larger threshold to show button earlier
  const atBottom = isScrolledToBottom(container, SCROLL_BUTTON_SHOW_THRESHOLD_PX);
  scrollButton.classList.toggle('hidden', atBottom);
}

/**
 * Manually trigger visibility check (useful after rendering new messages)
 */
export function checkScrollButtonVisibility(): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    updateScrollButtonVisibility(messagesContainer);
  }
}

/**
 * Set the streaming paused state for the scroll button.
 * When streaming is active and auto-scroll is paused (user scrolled up),
 * the button gets a highlighted appearance to indicate new content is available.
 * @param paused - Whether streaming auto-scroll is paused
 */
export function setStreamingPausedIndicator(paused: boolean): void {
  isStreamingPaused = paused;
  if (scrollButton) {
    scrollButton.classList.toggle('streaming-paused', paused);
  }
}

/**
 * Get the current streaming paused state
 */
export function isStreamingAutoScrollPaused(): boolean {
  return isStreamingPaused;
}