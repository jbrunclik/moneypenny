// DOM utility functions

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

/**
 * Cancel any ongoing smooth scroll animation.
 * Call this when user scrolls or when scroll mode is disabled.
 */
export function cancelSmoothScroll(): void {
  if (currentSmoothScrollAnimationId !== null) {
    cancelAnimationFrame(currentSmoothScrollAnimationId);
    currentSmoothScrollAnimationId = null;
  }
}

/**
 * Scroll element to bottom
 */
export function scrollToBottom(element: HTMLElement, smooth = false): void {
  // Cancel any ongoing smooth scroll animation before starting a new scroll
  cancelSmoothScroll();

  if (!smooth) {
    element.scrollTo({
      top: element.scrollHeight,
      behavior: 'auto',
    });
    return;
  }

  // Custom smooth scroll with easing for better animation
  const start = element.scrollTop;
  const target = element.scrollHeight - element.clientHeight;
  const distance = target - start;
  const duration = Math.min(600, Math.max(300, Math.abs(distance) * 0.5)); // 300-600ms based on distance
  const startTime = performance.now();

  // Easing function: ease-out-cubic
  const easeOutCubic = (t: number): number => {
    return 1 - Math.pow(1 - t, 3);
  };

  const animate = (currentTime: number): void => {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = easeOutCubic(progress);

    element.scrollTop = start + distance * eased;

    if (progress < 1) {
      currentSmoothScrollAnimationId = requestAnimationFrame(animate);
    } else {
      // Animation complete, clear the ID
      currentSmoothScrollAnimationId = null;
    }
  };

  currentSmoothScrollAnimationId = requestAnimationFrame(animate);
}

/**
 * Check if element is scrolled to bottom (within threshold)
 */
export function isScrolledToBottom(element: HTMLElement, threshold = 100): boolean {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight < threshold
  );
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