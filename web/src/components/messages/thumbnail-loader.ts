/**
 * Thumbnail lazy loading: an IntersectionObserver hands images that scroll
 * into view to a concurrency-limited fetch queue, which sets a blob URL and
 * marks the image loaded or errored. The image-load scroll mode listens in
 * through setThumbnailLoadHooks.
 */
import { files } from '../../api/files';
import { createLogger } from '../../utils/logger';
import { trackBlobUrl, untrackBlobUrl } from '../../utils/thumbnail-blob-urls';
import {
    THUMBNAIL_MAX_CONCURRENT_FETCHES,
    INTERSECTION_OBSERVER_ROOT_MARGIN,
    INTERSECTION_OBSERVER_THRESHOLD,
} from '../../config';

const log = createLogger('thumbnail-loader');
const loadingQueue: Array<() => Promise<void>> = [];
let activeFetches = 0;

// Flag to defer image observation until after counting
// Used in renderMessages() to prevent IntersectionObserver from firing before we count
let deferImageObservation = false;

/** Callbacks into the image-load scroll mode (see image-load-scroll.ts). */
export interface ThumbnailLoadHooks {
    /** A visible image is about to be fetched. */
    onLoadStart: (img: HTMLImageElement) => void;
    /** A fetched image finished loading - or failed (`isError`). */
    onLoadEnd: (isError: boolean) => void;
}

let loadHooks: ThumbnailLoadHooks | null = null;

/** Register the callbacks fired around each thumbnail load. */
export function setThumbnailLoadHooks(hooks: ThumbnailLoadHooks): void {
    loadHooks = hooks;
}

/**
 * Set flag to defer image observation until after counting.
 * Used in renderMessages() to prevent IntersectionObserver from firing before we count.
 */
export function setDeferImageObservation(defer: boolean): void {
    deferImageObservation = defer;
}
/**
 * Process the loading queue with concurrency limit
 */
function processQueue(): void {
    while (activeFetches < THUMBNAIL_MAX_CONCURRENT_FETCHES && loadingQueue.length > 0) {
        const task = loadingQueue.shift();
        if (task) {
            activeFetches++;
            void task().finally(() => {
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
                        // Let the image-load scroll mode count this load
                        loadHooks?.onLoadStart(img);

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

                                // The image-load scroll mode may scroll now
                                loadHooks?.onLoadEnd(false);

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

                                // A failed load counts as done too (same path as success)
                                loadHooks?.onLoadEnd(true);
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
