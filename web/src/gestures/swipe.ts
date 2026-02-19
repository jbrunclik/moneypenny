// Swipe gesture handler for touch devices

export interface SwipeConfig {
  /** Check if swipe should start for this touch event */
  shouldStart: (e: TouchEvent) => boolean;
  /** Get the element to apply transform to */
  getTarget: (e: TouchEvent) => HTMLElement | null;
  /** Calculate transform string based on deltaX */
  getTransform: (
    deltaX: number,
    isOpen: boolean,
    config: { maxDistance: number; threshold: number }
  ) => string | null;
  /** Check if target is in "open" state */
  getInitialState: (target: HTMLElement) => boolean;
  /** Called during swipe movement */
  onSwipeMove?: (target: HTMLElement, deltaX: number, progress: number) => void;
  /** Called when swipe completes (crossed threshold) */
  onComplete: (target: HTMLElement, deltaX: number) => void;
  /** Called when snapping back (didn't cross threshold) */
  onSnapBack?: (target: HTMLElement) => void;
  /** Minimum distance to complete action */
  threshold?: number;
  /** Maximum swipe distance */
  maxDistance?: number;
  /** Minimum movement to start swipe */
  minMovement?: number;
}

export interface SwipeHandlers {
  handleTouchStart: (e: TouchEvent) => void;
  handleTouchMove: (e: TouchEvent) => void;
  handleTouchEnd: (e: TouchEvent) => boolean;
  handleTouchCancel: () => void;
}

/**
 * Create a reusable swipe handler with configurable behavior
 */
export function createSwipeHandler(config: SwipeConfig): SwipeHandlers {
  const {
    shouldStart,
    getTarget,
    getTransform,
    getInitialState,
    onSwipeMove,
    onComplete,
    onSnapBack,
    threshold = 50,
    maxDistance = 80,
    minMovement = 10,
  } = config;

  let swipeStartX = 0;
  let swipeStartY = 0;
  let swipeCurrentX = 0;
  let swipeTarget: HTMLElement | null = null;
  let isSwiping = false;
  let swipeStartTime = 0;

  const handleTouchStart = (e: TouchEvent): void => {
    if (!shouldStart(e)) return;

    swipeStartX = e.touches[0].clientX;
    swipeStartY = e.touches[0].clientY;
    swipeCurrentX = swipeStartX;
    swipeTarget = getTarget(e);
    isSwiping = false;
    swipeStartTime = Date.now();
  };

  const handleTouchMove = (e: TouchEvent): void => {
    if (!swipeTarget) return;

    swipeCurrentX = e.touches[0].clientX;
    const currentY = e.touches[0].clientY;
    const deltaX = swipeStartX - swipeCurrentX;
    const deltaY = Math.abs(swipeStartY - currentY);

    // Only start swiping if horizontal movement is greater than vertical
    if (Math.abs(deltaX) > minMovement && Math.abs(deltaX) > deltaY) {
      isSwiping = true;
    }

    if (isSwiping) {
      const isOpen = getInitialState(swipeTarget);
      const transform = getTransform(deltaX, isOpen, { maxDistance, threshold });

      if (transform !== null) {
        swipeTarget.style.transform = transform;
        swipeTarget.style.transition = 'none';

        if (onSwipeMove) {
          const progress = Math.min(Math.abs(deltaX) / maxDistance, 1);
          onSwipeMove(swipeTarget, deltaX, progress);
        }
      }
    }
  };

  const handleTouchEnd = (e: TouchEvent): boolean => {
    if (!swipeTarget) return false;

    const deltaX = swipeStartX - swipeCurrentX;
    const finalY = e.changedTouches[0]?.clientY ?? swipeStartY;
    const deltaY = Math.abs(swipeStartY - finalY);
    const timeElapsed = Date.now() - swipeStartTime;

    // Restore transition
    swipeTarget.style.transition = '';

    let handled: boolean;

    if (isSwiping && Math.abs(deltaX) > deltaY) {
      // It was a swipe
      handled = true;
      if (Math.abs(deltaX) > threshold) {
        // Swiped far enough - complete action
        swipeTarget.style.transform = '';
        onComplete(swipeTarget, deltaX);
      } else {
        // Snap back
        swipeTarget.style.transform = '';
        onSnapBack?.(swipeTarget);
      }
    } else if (
      !isSwiping &&
      timeElapsed < 300 &&
      Math.abs(deltaX) < 10 &&
      Math.abs(deltaY) < 10
    ) {
      // It was a tap - let it bubble up for normal click handling
      handled = false;
    } else {
      // Reset transform if it was just a scroll
      swipeTarget.style.transform = '';
      handled = true;
    }

    swipeTarget = null;
    isSwiping = false;
    return handled;
  };

  // Handle touch cancel (iOS Safari can cancel touches during gestures)
  const handleTouchCancel = (): void => {
    if (swipeTarget) {
      swipeTarget.style.transform = '';
      swipeTarget.style.transition = '';
    }
    swipeTarget = null;
    isSwiping = false;
  };

  return { handleTouchStart, handleTouchMove, handleTouchEnd, handleTouchCancel };
}

/**
 * Check if device supports touch
 */
export function isTouchDevice(): boolean {
  return window.matchMedia('(hover: none)').matches;
}

/**
 * Reset all swiped conversation items
 */
export function resetSwipeStates(
  exceptWrapper: HTMLElement | null = null
): void {
  document
    .querySelectorAll<HTMLElement>('.conversation-item-wrapper.swiped')
    .forEach((el) => {
      if (el !== exceptWrapper) {
        el.classList.remove('swiped');
        const convItem = el.querySelector<HTMLElement>('.conversation-item');
        if (convItem) {
          convItem.style.transform = '';
        }
      }
    });
}