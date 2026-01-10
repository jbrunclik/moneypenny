import { files } from '../api/client';
import { getElementById, scrollToBottom, isScrolledToBottom, cancelSmoothScroll } from './dom';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { createLogger } from './logger';
import {
    THUMBNAIL_MAX_CONCURRENT_FETCHES,
    SCROLL_PROGRAMMATIC_RESET_DELAY_MS,
    SCROLL_USER_DETECTION_THRESHOLD_PX,
    SCROLL_SMOOTH_COMPLETION_DELAY_MS,
    SCROLL_MODE_GRACE_PERIOD_MS,
    IMAGE_LOAD_RETRY_DELAY_MS,
    IMAGE_LOAD_MAX_RETRY_ATTEMPTS,
    INTERSECTION_OBSERVER_ROOT_MARGIN,
    INTERSECTION_OBSERVER_THRESHOLD,
} from '../config';

const log = createLogger('thumbnails');
const loadingQueue: Array<() => Promise<void>> = [];
let activeFetches = 0;

// Track blob URLs per message ID for cleanup on conversation switch
// Map<messageId, Set<blobUrl>>
const blobUrlsByMessage = new Map<string, Set<string>>();

// Track all blob URLs for the current conversation for bulk cleanup
let currentConversationId: string | null = null;

// Flag to indicate we should scroll to bottom after images load
// This is set when opening a conversation and cleared when switching away
let shouldScrollOnImageLoad = false;

// Guard to prevent multiple concurrent enableScrollOnImageLoad calls
let isEnablingScrollMode = false;

/**
 * Track a blob URL for a message.
 * This allows cleanup when the conversation is switched.
 */
function trackBlobUrl(messageId: string, url: string): void {
    let urls = blobUrlsByMessage.get(messageId);
    if (!urls) {
        urls = new Set();
        blobUrlsByMessage.set(messageId, urls);
    }
    urls.add(url);
}

/**
 * Untrack a blob URL when it's been cleaned up via MutationObserver.
 */
function untrackBlobUrl(messageId: string, url: string): void {
    const urls = blobUrlsByMessage.get(messageId);
    if (urls) {
        urls.delete(url);
        if (urls.size === 0) {
            blobUrlsByMessage.delete(messageId);
        }
    }
}

/**
 * Clean up all tracked blob URLs for a conversation.
 * Called when switching conversations to prevent memory leaks.
 * @param conversationId - Optional: the conversation ID being switched away from (for logging)
 */
export function cleanupBlobUrlsForConversation(conversationId?: string): void {
    if (blobUrlsByMessage.size === 0) {
        return;
    }

    let cleanedCount = 0;
    for (const urls of blobUrlsByMessage.values()) {
        for (const url of urls) {
            URL.revokeObjectURL(url);
            cleanedCount++;
        }
    }
    blobUrlsByMessage.clear();

    if (cleanedCount > 0) {
        log.debug('Cleaned up blob URLs on conversation switch', {
            conversationId,
            cleanedCount,
        });
    }

    // Update the current conversation tracking
    currentConversationId = null;
}

/**
 * Set the current conversation ID for blob URL tracking.
 * Called when switching to a new conversation.
 */
export function setCurrentConversationForBlobs(conversationId: string | null): void {
    // If switching to a different conversation, clean up the old one's blob URLs
    if (currentConversationId && currentConversationId !== conversationId) {
        cleanupBlobUrlsForConversation(currentConversationId);
    }
    currentConversationId = conversationId;
}

// Flag to defer image observation until after counting
// Used in renderMessages() to prevent IntersectionObserver from firing before we count
let deferImageObservation = false;

// Track pending image loads for debounced scroll
let pendingImageLoads = 0;
let scrollTimeout: number | undefined;

// Flag to prevent user scroll listener from disabling scroll mode while we're scheduling a scroll
// This prevents race conditions where layout changes from image loading trigger the scroll listener
let isSchedulingScroll = false;

// Track user scroll to disable auto-scroll when user is browsing history
let userScrollListener: (() => void) | null = null;

// Track previous scroll position for direction-based user scroll detection
// This prevents false positives when images loading above viewport increase scrollHeight
let previousScrollTopForImageLoad = 0;

// Global flag to mark programmatic scrolls - set this before any scroll operation
// and it will be checked by the scroll listener
let isProgrammaticScroll = false;
let programmaticScrollResetTimeout: number | undefined;

/**
 * Mark the start of a programmatic scroll.
 * Call this before any scroll operation to prevent the scroll listener from
 * treating it as a user scroll.
 */
export function markProgrammaticScrollStart(): void {
    isProgrammaticScroll = true;
    // Clear any pending reset
    if (programmaticScrollResetTimeout) {
        clearTimeout(programmaticScrollResetTimeout);
    }
}

/**
 * Mark the end of a programmatic scroll.
 * Call this after any scroll operation completes.
 */
export function markProgrammaticScrollEnd(): void {
    // Use a small delay to ensure scroll events have fired
    programmaticScrollResetTimeout = window.setTimeout(() => {
        isProgrammaticScroll = false;
        programmaticScrollResetTimeout = undefined;
    }, SCROLL_PROGRAMMATIC_RESET_DELAY_MS);
}

/**
 * Perform a programmatic scroll to bottom that won't trigger user scroll detection.
 * This is a convenience wrapper that handles the markers automatically.
 * @param element The element to scroll
 * @param smooth Whether to use smooth scrolling
 */
export function programmaticScrollToBottom(element: HTMLElement, smooth = false): void {
    markProgrammaticScrollStart();
    scrollToBottom(element, smooth);

    if (smooth) {
        // Smooth scroll takes 300-600ms, wait a bit longer to ensure completion
        setTimeout(() => {
            markProgrammaticScrollEnd();
        }, SCROLL_SMOOTH_COMPLETION_DELAY_MS);
    } else {
        // Instant scroll completes immediately
        markProgrammaticScrollEnd();
    }
}

/**
 * Enable scroll-to-bottom behavior when images load.
 * Called when opening a conversation.
 * Automatically disables when user scrolls (indicating they want to view history).
 */
export function enableScrollOnImageLoad(): void {
    // Guard against rapid concurrent calls during conversation switching
    // This prevents multiple scroll listeners from being set up during a single call
    if (isEnablingScrollMode) {
        log.debug('enableScrollOnImageLoad: already enabling, skipping');
        return;
    }
    isEnablingScrollMode = true;

    try {
        // First, clean up any existing scroll listener to prevent duplicates
        removeUserScrollListener();

        shouldScrollOnImageLoad = true;
        pendingImageLoads = 0;
        deferImageObservation = false;
        isSchedulingScroll = false; // Reset scheduling flag
        if (scrollTimeout) {
            cancelAnimationFrame(scrollTimeout);
            scrollTimeout = undefined;
        }

        // Initialize previous scroll position for direction-based detection
        const messagesContainer = getElementById<HTMLDivElement>('messages');
        if (messagesContainer) {
            previousScrollTopForImageLoad = messagesContainer.scrollTop;
        }

        // Track when scroll mode was enabled to prevent false positives from initial scroll
        if (typeof window !== 'undefined') {
            (window as Window & { __scrollModeEnabledTime?: number }).__scrollModeEnabledTime = Date.now();
        }

        // Set up listener to disable scroll mode when user scrolls
        setupUserScrollListener();
    } finally {
        // Clear the guard immediately after the synchronous operation completes
        // The guard only prevents concurrent re-entry, not sequential calls
        isEnablingScrollMode = false;
    }
}

/**
 * Get the current pending image loads count.
 * Used for debugging and to check if we need to trigger scroll.
 */
export function getPendingImageLoads(): number {
    return pendingImageLoads;
}

/**
 * Set flag to defer image observation until after counting.
 * Used in renderMessages() to prevent IntersectionObserver from firing before we count.
 */
export function setDeferImageObservation(defer: boolean): void {
    deferImageObservation = defer;
}

/**
 * Count visible images that need loading after rendering and scroll.
 * This handles cached images that load instantly.
 * Should be called after renderMessages() completes and scroll has happened.
 * This counts images that became visible after the scroll (images at the bottom).
 */
export function countVisibleImagesForScroll(): void {
    if (!shouldScrollOnImageLoad) return;

    const messagesContainer = getElementById<HTMLDivElement>('messages');
    if (!messagesContainer) return;

    // CRITICAL FIX: If pendingImageLoads is already 0, check if all images are loaded
    // This handles the case where images loaded instantly (from cache) before we could count them
    // We need to check ALL images (not just tracked ones) because cached images might not be tracked yet
    if (pendingImageLoads === 0) {
        const allImages = messagesContainer.querySelectorAll<HTMLImageElement>(
            'img[data-message-id][data-file-index]'
        );
        if (allImages.length > 0) {
            let allLoaded = true;
            let imagesNeedingLoad = 0;
            allImages.forEach((img) => {
                // More lenient check: if image has src and is complete, consider it loaded
                // even if naturalHeight is 0 (could be a 1x1 transparent pixel or broken image)
                // The key is that it has src and complete, meaning the browser tried to load it
                if (!img.src || !img.complete) {
                    allLoaded = false;
                    if (!img.src) {
                        imagesNeedingLoad++;
                    }
                }
            });
            // If all images are loaded OR if there are no images needing load (all have src),
            // schedule scroll. This handles the cached image case.
            if (allLoaded || imagesNeedingLoad === 0) {
                scheduleScrollAfterImageLoad();
                return;
            }
        }
    }

    // Find all images that need loading (without src)
    const imagesWithoutSrc = messagesContainer.querySelectorAll<HTMLImageElement>(
        'img[data-message-id][data-file-index]:not([src])'
    );

    // Also find all tracked images (they might have loaded instantly)
    const allTrackedImages = messagesContainer.querySelectorAll<HTMLImageElement>(
        'img[data-message-id][data-file-index][data-scroll-tracked]'
    );

    // If no images need loading, check tracked images to see if they're all done
    if (imagesWithoutSrc.length === 0) {
        // All images have src - check if any tracked images are still loading
        let allLoaded = true;
        let trackedCount = 0;
        allTrackedImages.forEach((img) => {
            trackedCount++;
            if (!img.complete || img.naturalHeight === 0) {
                allLoaded = false;
            }
        });

        // If we have tracked images but pendingImageLoads is 0, we might have a race condition
        // where images loaded before we could count them properly
        // In this case, if all images are loaded, trigger scroll
        if (trackedCount > 0 && allLoaded && pendingImageLoads === 0) {
            scheduleScrollAfterImageLoad();
        }
        return;
    }

    // Count ALL visible images that need loading (not just ones that became visible after scroll)
    // On initial load, all images are "new" so we need to count all visible ones
    let foundVisible = false;
    imagesWithoutSrc.forEach((img) => {
        // Check if already tracked (to avoid double-counting)
        if (img.dataset.scrollTracked) return;

        const rect = img.getBoundingClientRect();
        const containerRect = messagesContainer.getBoundingClientRect();
        const isVisible =
            rect.top < containerRect.bottom && rect.bottom > containerRect.top;

        if (isVisible) {
            foundVisible = true;
            // Image is visible - increment and mark to prevent double-counting
            incrementPendingImageLoads();
            img.dataset.scrollTracked = 'true';

            // If image already has src AND is complete (loaded from cache), decrement immediately
            // This handles the race where cached images load before IntersectionObserver fires
            // NOTE: img.complete is true for images without src (per MDN), so we must check BOTH
            if (img.src && img.complete) {
                pendingImageLoads = Math.max(0, pendingImageLoads - 1);
            }
        }
    });

    // Special handling for the 2-image race condition on initial load:
    // If we counted visible images but pendingImageLoads is 0, it means:
    // 1. All images loaded instantly (cached), OR
    // 2. IntersectionObserver already fired and decremented before we counted
    // In either case, check if all tracked images are actually loaded before triggering scroll
    if (foundVisible && pendingImageLoads === 0) {
        // Collect all tracked images (from both queries)
        const allTracked = new Set<HTMLImageElement>();
        allTrackedImages.forEach((img) => allTracked.add(img));
        imagesWithoutSrc.forEach((img) => {
            if (img.dataset.scrollTracked) {
                allTracked.add(img);
            }
        });

        // Check if all tracked images are actually loaded
        let allTrackedLoaded = true;
        allTracked.forEach((img) => {
            // More lenient check: if image has src and is complete, consider it loaded
            // even if naturalHeight is 0 (could be a 1x1 transparent pixel or broken image)
            if (!img.src || !img.complete) {
                allTrackedLoaded = false;
            }
        });

        if (allTrackedLoaded && allTracked.size > 0) {
            scheduleScrollAfterImageLoad();
        }
    } else if (!foundVisible && pendingImageLoads === 0) {
        // No visible images to load, but pendingImageLoads is 0 - check if all tracked images are done
        let allTrackedLoaded = true;
        allTrackedImages.forEach((img) => {
            // More lenient check: if image has src and is complete, consider it loaded
            if (!img.src || !img.complete) {
                allTrackedLoaded = false;
            }
        });
        if (allTrackedLoaded) {
            scheduleScrollAfterImageLoad();
        }
    }
}

/**
 * Get tracked images that need to be checked for loading state.
 * Only returns images marked with data-scroll-tracked (visible images that were counted).
 * We only need to wait for VISIBLE images to load before scrolling - images above
 * the viewport will lazy-load when the user scrolls up.
 */
function getTrackedImagesToCheck(container: HTMLElement): Set<HTMLImageElement> {
    const trackedImages = container.querySelectorAll<HTMLImageElement>(
        'img[data-message-id][data-file-index][data-scroll-tracked]'
    );

    const imagesToCheck = new Set<HTMLImageElement>();
    trackedImages.forEach((img) => imagesToCheck.add(img));
    return imagesToCheck;
}

/**
 * Check if all tracked (visible) images are loaded (have src and are complete).
 * Returns an object with loading state information.
 */
function checkTrackedImagesLoaded(container: HTMLElement): {
    allLoaded: boolean;
    imagesWithoutSrc: number;
    totalImages: number;
} {
    const imagesToCheck = getTrackedImagesToCheck(container);
    let allLoaded = true;
    let imagesWithoutSrc = 0;

    imagesToCheck.forEach((img) => {
        // More lenient check: if image has src and is complete, consider it loaded
        if (!img.src || !img.complete) {
            allLoaded = false;
            if (!img.src) {
                imagesWithoutSrc++;
            }
        }
    });

    return {
        allLoaded,
        imagesWithoutSrc,
        totalImages: imagesToCheck.size,
    };
}

/**
 * Ensure all visible images without src are observed.
 * IntersectionObserver might not have fired yet, so we manually observe them.
 */
function observeUnobservedVisibleImages(container: HTMLElement): void {
    const unobservedImages = container.querySelectorAll<HTMLImageElement>(
        'img[data-message-id][data-file-index]:not([src])'
    );
    unobservedImages.forEach((img) => {
        const rect = img.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        const isVisible =
            rect.top < containerRect.bottom && rect.bottom > containerRect.top;
        if (isVisible) {
            // Observe this image to trigger IntersectionObserver
            observeThumbnail(img);
        }
    });
}

/**
 * Retry checking if all images are loaded, with a maximum number of attempts.
 * This handles race conditions where images load in quick succession or cached images
 * need time to fully decode.
 */
function retryImageLoadCheck(
    container: HTMLElement,
    attempt: number,
    trackedCount: number
): void {
    if (!shouldScrollOnImageLoad) return;
    if (attempt >= IMAGE_LOAD_MAX_RETRY_ATTEMPTS) {
        return;
    }

    // Ensure all visible images without src are observed
    observeUnobservedVisibleImages(container);

    const { allLoaded, totalImages } = checkTrackedImagesLoaded(container);

    if (allLoaded && totalImages > 0) {
        scheduleScrollAfterImageLoad();
    } else if (totalImages > 0) {
        // Still not all loaded - retry after delay
        setTimeout(() => {
            retryImageLoadCheck(container, attempt + 1, trackedCount);
        }, IMAGE_LOAD_RETRY_DELAY_MS);
    }
}

/**
 * Handle image load completion (both success and error cases).
 * Checks scroll position, decrements pending loads, and schedules scroll if needed.
 */
function handleImageLoadCompletion(
    messagesContainer: HTMLElement | null,
    _isError: boolean
): void {
    if (!shouldScrollOnImageLoad) {
        return;
    }

    // Always decrement pendingImageLoads, regardless of scroll position.
    //
    // IMPORTANT: We removed the per-image "wasAtBottom" check because it caused false
    // positives when images ABOVE the viewport load. When an image above loads:
    // 1. scrollHeight increases but scrollTop stays the same
    // 2. The user appears "not at bottom" even though they didn't scroll
    // 3. Scroll mode was incorrectly disabled
    //
    // The scroll listener (setupUserScrollListener) handles detecting actual user scrolls.
    // The final position check happens in scheduleScrollAfterImageLoad after ALL images load.
    pendingImageLoads = Math.max(0, pendingImageLoads - 1);

    if (!messagesContainer) {
        if (pendingImageLoads === 0) {
            scheduleScrollAfterImageLoad();
        }
        return;
    }

    // If pendingImageLoads is 0, check if all tracked images are actually loaded
    // This handles race conditions where images load before we count them
    if (pendingImageLoads === 0) {
        const trackedImages = messagesContainer.querySelectorAll<HTMLImageElement>(
            'img[data-message-id][data-file-index][data-scroll-tracked]'
        );
        const { allLoaded, totalImages } = checkTrackedImagesLoaded(messagesContainer);

        // Only schedule scroll if ALL images are actually loaded (complete).
        // Don't schedule if images just have src but aren't complete yet - wait for them to finish loading.
        if (allLoaded && totalImages > 0) {
            scheduleScrollAfterImageLoad();
        } else {
            // Some images don't have src yet or aren't complete - retry with delay
            // Retry after delay to handle race conditions
            setTimeout(() => {
                retryImageLoadCheck(messagesContainer, 1, trackedImages.length);
            }, IMAGE_LOAD_RETRY_DELAY_MS);
        }
    } else {
        // pendingImageLoads > 0, so images are still loading - schedule scroll when they complete
        scheduleScrollAfterImageLoad();
    }
}

/**
 * Disable scroll-to-bottom behavior.
 *
 * Note: With direction-based detection in setupUserScrollListener, we no longer need
 * to check isSchedulingScroll here. Direction-based detection only triggers on actual
 * user scroll UP (scrollTop decreases), which cannot be caused by layout changes.
 */
function safelyDisableScrollOnImageLoad(reason: string): void {
    log.debug('safelyDisableScrollOnImageLoad called', { reason, shouldScrollOnImageLoad, isSchedulingScroll });
    shouldScrollOnImageLoad = false;
    pendingImageLoads = 0;
    if (scrollTimeout) {
        cancelAnimationFrame(scrollTimeout);
        scrollTimeout = undefined;
    }
    // Cancel any ongoing smooth scroll animation to prevent it from
    // fighting with user scroll or other scroll operations
    cancelSmoothScroll();
    removeUserScrollListener();
}

/**
 * Disable scroll-to-bottom behavior.
 * Called when switching conversations or creating new chat.
 */
export function disableScrollOnImageLoad(): void {
    safelyDisableScrollOnImageLoad('explicit disable');
}

/**
 * Set up a scroll listener that disables scroll-on-image-load when user scrolls UP.
 * This prevents hijacking the scroll position when user is browsing history.
 *
 * CRITICAL: Uses direction-based detection (like streaming scroll listener in Messages.ts).
 * Only disables when scrollTop DECREASES (user scrolled up), not when distanceFromBottom
 * increases due to images loading above viewport (which increases scrollHeight but
 * keeps scrollTop the same).
 *
 * Why direction-based:
 * - When an image ABOVE the viewport loads, scrollHeight increases
 * - Browser maintains scrollTop (position relative to content above)
 * - distanceFromBottom increases even though user never scrolled
 * - Position-based detection would falsely disable scroll mode
 * - Direction-based detection only triggers on actual user scroll UP
 */
function setupUserScrollListener(): void {
    // Remove any existing listener first
    removeUserScrollListener();

    const messagesContainer = getElementById<HTMLDivElement>('messages');
    if (!messagesContainer) return;

    userScrollListener = () => {
        // iOS Safari momentum scroll can cause scrollTop to temporarily go negative
        // (rubber-banding at top) or past the max (rubber-banding at bottom).
        // Ignore these out-of-bounds values to prevent false user-scroll detection.
        const currentScrollTop = messagesContainer.scrollTop;
        const maxScrollTop = messagesContainer.scrollHeight - messagesContainer.clientHeight;
        if (currentScrollTop < 0 || currentScrollTop > maxScrollTop) {
            return; // Ignore rubber-banding scroll events
        }

        // Direction-based detection: only disable if user scrolled UP
        // Our programmatic scrollToBottom() never scrolls up, so this is definitely user action
        const scrolledUp = currentScrollTop < previousScrollTopForImageLoad;

        // CRITICAL: Always update previous scroll position, even during programmatic scrolls.
        // This ensures we have the correct baseline for detecting the next scroll direction.
        // If we only updated during user scrolls, after a programmatic scroll to bottom,
        // previousScrollTopForImageLoad would still be 0, and scrolling to 0 wouldn't be detected as "up".
        previousScrollTopForImageLoad = currentScrollTop;

        // Ignore programmatic scrolls for the disable decision (but we still updated the position above)
        if (isProgrammaticScroll) {
            return;
        }

        if (!scrolledUp) {
            return; // User scrolled down or stayed in place - don't disable
        }

        // User scrolled UP - this is definitely a user action
        // Direction-based detection eliminates false positives from layout changes
        // (layout changes from image loading never decrease scrollTop)

        // Check if scroll mode was just enabled (within grace period)
        // This prevents false positives from initial scroll in renderMessages()
        const scrollModeEnabledTime = (window as Window & { __scrollModeEnabledTime?: number }).__scrollModeEnabledTime;
        if (
            scrollModeEnabledTime &&
            Date.now() - scrollModeEnabledTime < SCROLL_MODE_GRACE_PERIOD_MS
        ) {
            return;
        }

        // User definitely scrolled up - disable scroll mode
        safelyDisableScrollOnImageLoad('user scrolled up');
    };

    messagesContainer.addEventListener('scroll', userScrollListener, { passive: true });
}

/**
 * Remove the user scroll listener.
 */
function removeUserScrollListener(): void {
    if (userScrollListener) {
        const messagesContainer = getElementById<HTMLDivElement>('messages');
        if (messagesContainer) {
            messagesContainer.removeEventListener('scroll', userScrollListener);
        }
        userScrollListener = null;
    }
}

/**
 * Check if scroll-on-image-load is currently enabled.
 * Used to determine if we should delay initial scroll in renderMessages.
 */
export function isScrollOnImageLoadEnabled(): boolean {
    return shouldScrollOnImageLoad;
}

/**
 * Increment pending image loads counter.
 * Used when pre-counting visible images to handle cached images.
 */
export function incrementPendingImageLoads(): void {
    if (shouldScrollOnImageLoad) {
        pendingImageLoads++;
    }
}

/**
 * Schedule a scroll to bottom after all images have loaded.
 * Uses debouncing to wait for all concurrent image loads to complete.
 */
function scheduleScrollAfterImageLoad(): void {
    log.debug('scheduleScrollAfterImageLoad called', { shouldScrollOnImageLoad, isSchedulingScroll });

    if (!shouldScrollOnImageLoad) {
        log.debug('scheduleScrollAfterImageLoad: shouldScrollOnImageLoad is false, returning');
        return;
    }

    // Clear any existing timeout
    if (scrollTimeout) {
        cancelAnimationFrame(scrollTimeout);
    }

    // Set flag to prevent user scroll listener from disabling scroll mode
    // This MUST be set before any async operations to prevent race conditions
    isSchedulingScroll = true;
    log.debug('scheduleScrollAfterImageLoad: scheduling RAFs');

    // Wait for a short period after the last image load to ensure all images have rendered
    // This handles the case where multiple images are loading concurrently
    // Use multiple RAFs to ensure layout has fully settled before starting smooth scroll
    // CRITICAL: Check shouldScrollOnImageLoad at each level because cancelAnimationFrame
    // only cancels the outermost RAF - inner ones continue if outer has already fired
    scrollTimeout = requestAnimationFrame(() => {
        if (!shouldScrollOnImageLoad) {
            isSchedulingScroll = false;
            scrollTimeout = undefined;
            return;
        }
        requestAnimationFrame(() => {
            if (!shouldScrollOnImageLoad) {
                isSchedulingScroll = false;
                scrollTimeout = undefined;
                return;
            }
            requestAnimationFrame(() => {
                // Wrap the entire callback in try/finally to ensure isSchedulingScroll is always reset on error
                try {
                    // Re-check conditions before scrolling - user might have scrolled up while images were loading
                    if (!shouldScrollOnImageLoad) {
                        isSchedulingScroll = false;
                        scrollTimeout = undefined;
                        return;
                    }

                    // Double-check isSchedulingScroll is still true (should be, but verify)
                    if (!isSchedulingScroll) {
                        // Re-set it since we're about to scroll
                        isSchedulingScroll = true;
                    }

                    const messagesContainer = getElementById<HTMLDivElement>('messages');
                    if (!messagesContainer) {
                        isSchedulingScroll = false;
                        scrollTimeout = undefined;
                        return;
                    }

                    // CRITICAL FIX: Don't check pendingImageLoads here - if we scheduled scroll,
                    // it means all images are loaded. The counter might be 0 due to race conditions.
                    // Instead, verify that all tracked images are actually loaded before scrolling.
                    const allTrackedImages = messagesContainer.querySelectorAll<HTMLImageElement>(
                        'img[data-message-id][data-file-index][data-scroll-tracked]'
                    );
                    let allLoaded = true;
                    allTrackedImages.forEach((img) => {
                        // More lenient check: if image has src and is complete, consider it loaded
                        // even if naturalHeight is 0 (could be a 1x1 transparent pixel or broken image)
                        if (!img.src || !img.complete) {
                            allLoaded = false;
                        }
                    });

                    if (!allLoaded && allTrackedImages.length > 0) {
                        // Wait a bit more and check again
                        scrollTimeout = requestAnimationFrame(() => {
                            requestAnimationFrame(() => {
                                // Don't clear flag before recursive call - keep it true during the entire scheduling process
                                // The recursive call will re-check and either scroll or wait again
                                scheduleScrollAfterImageLoad();
                            });
                        });
                        return;
                    }

                    // Only scroll if user is still at or near the bottom
                    // This prevents hijacking scroll when user is browsing history
                    // BUT: If we're scheduling a scroll, don't check isAtBottom because layout changes
                    // from images loading can temporarily make it appear user scrolled away
                    const isAtBottom = isScrolledToBottom(messagesContainer, SCROLL_USER_DETECTION_THRESHOLD_PX);
                    if (!isAtBottom && !isSchedulingScroll) {
                        // Only disable if we're NOT scheduling a scroll
                        // If we're scheduling, layout changes from images might be causing false positives
                        // User has scrolled up - disable scroll mode and don't scroll
                        safelyDisableScrollOnImageLoad('user scrolled away during scroll scheduling');
                        isSchedulingScroll = false;
                        scrollTimeout = undefined;
                        return;
                    } else if (!isAtBottom && isSchedulingScroll) {
                        // We're scheduling a scroll but user appears to have scrolled away
                        // This is likely a false positive from layout changes - ignore it
                    }

                    // Mark this as a programmatic scroll so we don't disable on our own scroll
                    log.debug('scheduleScrollAfterImageLoad: about to scroll to bottom', {
                        scrollTop: messagesContainer.scrollTop,
                        scrollHeight: messagesContainer.scrollHeight,
                        clientHeight: messagesContainer.clientHeight,
                    });
                    markProgrammaticScrollStart();
                    // Use smooth scroll to avoid abrupt flashing
                    scrollToBottom(messagesContainer, true);
                    // End programmatic scroll after animation completes (smooth scroll takes 300-600ms)
                    // Also clear the scheduling flag after scroll completes to prevent false positives
                    setTimeout(() => {
                        markProgrammaticScrollEnd();
                        isSchedulingScroll = false; // Clear flag after scroll animation completes
                    }, SCROLL_SMOOTH_COMPLETION_DELAY_MS);
                    // Update button visibility after scrolling
                    requestAnimationFrame(() => {
                        checkScrollButtonVisibility();
                    });
                    scrollTimeout = undefined;
                } catch (error) {
                    // CRITICAL: Always reset isSchedulingScroll on error to prevent permanent blocking
                    log.error('Error in scheduleScrollAfterImageLoad', { error });
                    isSchedulingScroll = false;
                    scrollTimeout = undefined;
                }
            });
        });
    });
}

/**
 * Process the loading queue with concurrency limit
 */
function processQueue(): void {
    while (activeFetches < THUMBNAIL_MAX_CONCURRENT_FETCHES && loadingQueue.length > 0) {
        const task = loadingQueue.shift();
        if (task) {
            activeFetches++;
            task().finally(() => {
                activeFetches--;
                processQueue();
            });
        }
    }
}

/**
 * Queue a thumbnail load with concurrency limiting
 */
function queueLoad(loadFn: () => Promise<void>): void {
    loadingQueue.push(loadFn);
    processQueue();
}

/**
 * Create an Intersection Observer for lazy loading images
 */
export function createThumbnailObserver(): IntersectionObserver {
    return new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    const img = entry.target as HTMLImageElement;
                    const messageId = img.dataset.messageId;
                    const fileIndex = img.dataset.fileIndex;

                    if (messageId && fileIndex) {
                        // Track this image load if we're in scroll mode
                        // Check if we already tracked it (to avoid double-counting for cached images)
                        if (shouldScrollOnImageLoad && !img.dataset.scrollTracked) {
                            pendingImageLoads++;
                            img.dataset.scrollTracked = 'true';
                        }

                        queueLoad(async () => {
                            try {
                                const blob = await files.fetchThumbnail(
                                    messageId,
                                    parseInt(fileIndex, 10)
                                );
                                const url = URL.createObjectURL(blob);
                                img.src = url;

                                // Track blob URL for cleanup on conversation switch
                                trackBlobUrl(messageId, url);

                                // Wait for the image to actually load and render
                                await new Promise<void>((resolve) => {
                                    if (img.complete && img.naturalHeight !== 0) {
                                        // Image already loaded
                                        resolve();
                                    } else {
                                        img.addEventListener('load', () => resolve(), { once: true });
                                        img.addEventListener('error', () => resolve(), { once: true });
                                    }
                                });

                                // Remove loading state from wrapper (if exists) or image
                                const wrapper = img.closest('.message-image-wrapper');
                                if (wrapper) {
                                    wrapper.classList.remove('loading');
                                }
                                img.classList.remove('loading');
                                img.classList.add('loaded');

                                // Decrement pending loads and schedule scroll
                                // Check both the flag AND scroll position to prevent race conditions
                                // (user might have scrolled up while image was loading)
                                if (shouldScrollOnImageLoad) {
                                    const messagesContainer = getElementById<HTMLDivElement>('messages');
                                    handleImageLoadCompletion(messagesContainer, false);
                                }

                                // Clean up blob URL when image is removed from DOM
                                const cleanup = () => {
                                    untrackBlobUrl(messageId, url);
                                    URL.revokeObjectURL(url);
                                };

                                // Use MutationObserver to detect removal
                                const parent = img.parentElement;
                                if (parent) {
                                    const mutationObserver = new MutationObserver((mutations) => {
                                        for (const mutation of mutations) {
                                            if (mutation.removedNodes.length > 0) {
                                                for (let i = 0; i < mutation.removedNodes.length; i++) {
                                                    const node = mutation.removedNodes[i];
                                                    if (node === img || (node as Element).contains?.(img)) {
                                                        cleanup();
                                                        mutationObserver.disconnect();
                                                        return;
                                                    }
                                                }
                                            }
                                        }
                                    });
                                    mutationObserver.observe(parent, { childList: true, subtree: true });
                                }
                            } catch (error) {
                                log.error('Failed to load thumbnail', { error });
                                // Remove loading state from wrapper (if exists) or image
                                const wrapper = img.closest('.message-image-wrapper');
                                if (wrapper) {
                                    wrapper.classList.remove('loading');
                                    wrapper.classList.add('error');
                                }
                                img.classList.remove('loading');
                                img.classList.add('error');

                                // Decrement pending loads even on error, and schedule scroll
                                // Check both the flag AND scroll position to prevent race conditions
                                // Error path uses same logic as success path for consistency
                                if (shouldScrollOnImageLoad) {
                                    const messagesContainer = getElementById<HTMLDivElement>('messages');
                                    handleImageLoadCompletion(messagesContainer, true);
                                }
                            }
                        });
                    }

                    // Stop observing this image
                    thumbnailObserver?.unobserve(img);
                }
            });
        },
        {
            rootMargin: INTERSECTION_OBSERVER_ROOT_MARGIN,
            threshold: INTERSECTION_OBSERVER_THRESHOLD,
        }
    );
}

let thumbnailObserver: IntersectionObserver | null = null;

/**
 * Get or create the thumbnail observer
 */
export function getThumbnailObserver(): IntersectionObserver {
    if (!thumbnailObserver) {
        thumbnailObserver = createThumbnailObserver();
    }
    return thumbnailObserver;
}

/**
 * Observe an image element for lazy loading
 */
export function observeThumbnail(img: HTMLImageElement): void {
    // If observation is deferred, don't observe yet
    // It will be observed later after counting in renderMessages()
    if (deferImageObservation) {
        return;
    }
    getThumbnailObserver().observe(img);
}

/**
 * Clean up blob URLs when images are removed
 */
export function cleanupBlobUrl(url: string): void {
    if (url.startsWith('blob:')) {
        URL.revokeObjectURL(url);
    }
}