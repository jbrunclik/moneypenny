import { getElementById, isScrolledToBottom, scrollToBottom } from '../utils/dom';
import { CHEVRON_DOWN_ICON } from '../utils/icons';

let scrollButton: HTMLButtonElement | null = null;

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

  // Also listen for resize events (when content height changes, e.g., collapsing details)
  const resizeObserver = new ResizeObserver(() => {
    requestAnimationFrame(() => {
      updateScrollButtonVisibility(messagesContainer);
    });
  });
  resizeObserver.observe(messagesContainer);
}

/**
 * Update the visibility of the scroll-to-bottom button
 * Shows the button when user has scrolled up, hides when at bottom
 */
function updateScrollButtonVisibility(container: HTMLElement): void {
  if (!scrollButton) return;

  // Use a larger threshold (200px) to show button earlier
  const atBottom = isScrolledToBottom(container, 200);
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