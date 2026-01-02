import { getElementById } from '../utils/dom';
import { files } from '../api/client';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';

const log = createLogger('lightbox');

let currentBlobUrl: string | null = null;

/**
 * Initialize lightbox event handlers
 */
export function initLightbox(): void {
  const lightbox = getElementById<HTMLDivElement>('lightbox');
  const closeBtn = lightbox?.querySelector('.lightbox-close');

  // Close on button click
  closeBtn?.addEventListener('click', closeLightbox);

  // Close on backdrop click
  lightbox?.addEventListener('click', (e) => {
    if (e.target === lightbox) {
      closeLightbox();
    }
  });

  // Register with centralized Escape key handler
  registerPopupEscapeHandler('lightbox', closeLightbox);

  // Listen for custom lightbox:open events
  window.addEventListener('lightbox:open', ((e: CustomEvent) => {
    const { messageId, fileIndex } = e.detail;
    if (messageId && fileIndex !== undefined) {
      openLightbox(messageId, parseInt(fileIndex, 10));
    }
  }) as EventListener);
}

/**
 * Open lightbox with image from API
 */
export async function openLightbox(
  messageId: string,
  fileIndex: number
): Promise<void> {
  const lightbox = getElementById<HTMLDivElement>('lightbox');
  const img = getElementById<HTMLImageElement>('lightbox-img');

  if (!lightbox || !img) return;

  // Show lightbox with loading state
  lightbox.classList.remove('hidden');
  lightbox.classList.add('loading');
  img.src = '';

  try {
    // Fetch full image
    const blob = await files.fetchFile(messageId, fileIndex);

    // Clean up previous blob URL
    if (currentBlobUrl) {
      URL.revokeObjectURL(currentBlobUrl);
    }

    currentBlobUrl = URL.createObjectURL(blob);
    img.src = currentBlobUrl;
    lightbox.classList.remove('loading');
  } catch (error) {
    log.error('Failed to load image', { error, messageId, fileIndex });
    toast.error('Failed to load image.');
    closeLightbox();
  }
}

/**
 * Close lightbox
 */
export function closeLightbox(): void {
  const lightbox = getElementById<HTMLDivElement>('lightbox');
  const img = getElementById<HTMLImageElement>('lightbox-img');

  if (lightbox) {
    lightbox.classList.add('hidden');
    lightbox.classList.remove('loading');
  }

  if (img) {
    img.src = '';
  }

  // Clean up blob URL
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl);
    currentBlobUrl = null;
  }
}