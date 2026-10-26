/**
 * Blob URLs of fetched thumbnails, tracked per message so they are revoked
 * when their image leaves the DOM or the conversation changes.
 */
import { createLogger } from './logger';

const log = createLogger('thumbnail-blob-urls');

// Track blob URLs per message ID for cleanup on conversation switch
// Map<messageId, Set<blobUrl>>
const blobUrlsByMessage = new Map<string, Set<string>>();

// Track all blob URLs for the current conversation for bulk cleanup
let currentConversationId: string | null = null;

/**
 * Track a blob URL for a message.
 * This allows cleanup when the conversation is switched.
 */
export function trackBlobUrl(messageId: string, url: string): void {
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
export function untrackBlobUrl(messageId: string, url: string): void {
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

/**
 * Clean up blob URLs when images are removed
 */
export function cleanupBlobUrl(url: string): void {
    if (url.startsWith('blob:')) {
        URL.revokeObjectURL(url);
    }
}
