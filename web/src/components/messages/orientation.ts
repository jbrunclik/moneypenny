/**
 * Orientation change handling for preserving scroll position.
 */

import { getElementById } from '../../utils/dom';
import { createLogger } from '../../utils/logger';

const log = createLogger('messages');

// Track scroll position for orientation change handling
let savedScrollPercentage: number | null = null;
let orientationChangeCleanup: (() => void) | null = null;

/**
 * Initialize orientation change handler to preserve scroll position.
 * When device orientation changes, layout reflows can cause scroll position loss.
 * This saves the scroll position as a percentage before orientation change and
 * restores it after layout settles.
 */
export function initOrientationChangeHandler(): void {
  // Clean up any existing handler
  if (orientationChangeCleanup) {
    orientationChangeCleanup();
  }

  const handleOrientationChange = (): void => {
    const container = getElementById<HTMLDivElement>('messages');
    if (!container) return;

    // Save scroll position as a percentage of total scrollable height
    const maxScrollTop = container.scrollHeight - container.clientHeight;
    if (maxScrollTop > 0) {
      savedScrollPercentage = container.scrollTop / maxScrollTop;
    } else {
      savedScrollPercentage = 1; // At bottom if no scrollable content
    }

    log.debug('Orientation change: saved scroll percentage', { savedScrollPercentage });

    // After orientation change, layout will reflow. Wait for it to settle and restore position.
    // Use multiple RAFs + timeout to ensure layout has fully settled
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setTimeout(() => {
          if (savedScrollPercentage !== null) {
            const newMaxScrollTop = container.scrollHeight - container.clientHeight;
            if (newMaxScrollTop > 0) {
              container.scrollTop = savedScrollPercentage * newMaxScrollTop;
              log.debug('Orientation change: restored scroll position', {
                savedScrollPercentage,
                newScrollTop: container.scrollTop,
              });
            }
            savedScrollPercentage = null;
          }
        }, 100); // Small delay to ensure layout has fully settled
      });
    });
  };

  window.addEventListener('orientationchange', handleOrientationChange);

  // Also handle resize as fallback (some devices don't fire orientationchange)
  let resizeTimeout: number | undefined;
  let lastWidth = window.innerWidth;
  let lastHeight = window.innerHeight;

  const handleResize = (): void => {
    // Only act on significant dimension changes that indicate orientation change
    // (width/height swap, not keyboard opening which only changes height)
    const currentWidth = window.innerWidth;
    const currentHeight = window.innerHeight;

    const widthChanged = Math.abs(currentWidth - lastWidth) > 100;
    const heightChanged = Math.abs(currentHeight - lastHeight) > 100;
    const dimensionsSwapped =
      (lastWidth > lastHeight && currentHeight > currentWidth) ||
      (lastHeight > lastWidth && currentWidth > currentHeight);

    if (dimensionsSwapped || (widthChanged && heightChanged)) {
      // Clear any pending timeout and handle immediately
      if (resizeTimeout) {
        clearTimeout(resizeTimeout);
      }
      resizeTimeout = window.setTimeout(() => {
        handleOrientationChange();
        lastWidth = currentWidth;
        lastHeight = currentHeight;
      }, 50);
    } else {
      // Just update the last dimensions for future comparison
      lastWidth = currentWidth;
      lastHeight = currentHeight;
    }
  };

  window.addEventListener('resize', handleResize);

  orientationChangeCleanup = () => {
    window.removeEventListener('orientationchange', handleOrientationChange);
    window.removeEventListener('resize', handleResize);
    if (resizeTimeout) {
      clearTimeout(resizeTimeout);
    }
  };
}
