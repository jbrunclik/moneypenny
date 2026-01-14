/**
 * File attachments rendering for messages (images and documents).
 */

import { escapeHtml } from '../../utils/dom';
import { observeThumbnail } from '../../utils/thumbnails';
import { getFileIcon, DOWNLOAD_ICON } from '../../utils/icons';
import type { FileMetadata } from '../../types/api';

/**
 * Render files attached to a message
 */
export function renderMessageFiles(files: FileMetadata[], messageId: string): HTMLElement {
  const container = document.createElement('div');
  container.className = 'message-files';

  // Separate images from other files
  const images = files.filter((f) => f.type.startsWith('image/'));
  const documents = files.filter((f) => !f.type.startsWith('image/'));

  // Render images in horizontal gallery
  if (images.length > 0) {
    const gallery = document.createElement('div');
    gallery.className = 'message-images';

    images.forEach((file) => {
      const fileIndex = files.indexOf(file);
      const imgWrapper = document.createElement('div');
      imgWrapper.className = 'message-image-wrapper';

      const img = document.createElement('img');
      img.className = 'message-image';
      img.alt = file.name;
      img.dataset.messageId = file.messageId || messageId;
      img.dataset.fileIndex = String(file.fileIndex ?? fileIndex);

      // Mark images with temp IDs as pending (lightbox disabled until real ID received)
      const effectiveMessageId = file.messageId || messageId;
      if (effectiveMessageId.startsWith('temp-')) {
        img.dataset.pending = 'true';
      }

      // If we have a local preview URL (just-uploaded file), use it directly
      // Otherwise, use lazy loading to fetch thumbnail from server
      if (file.previewUrl) {
        img.src = file.previewUrl;
      } else {
        // Add loading state for server-fetched images
        imgWrapper.classList.add('loading');

        // Add placeholder with filename
        const placeholder = document.createElement('span');
        placeholder.className = 'image-placeholder';
        placeholder.textContent = file.name;
        imgWrapper.appendChild(placeholder);

        img.loading = 'lazy';

        // Set up lazy loading - remove loading class from wrapper when loaded
        img.addEventListener('load', () => {
          imgWrapper.classList.remove('loading');
        });

        // Observe the image for lazy loading
        // Note: During renderMessages(), we'll also observe after counting to ensure
        // we count before IntersectionObserver fires, but we still need to observe here
        // for cases where images are added outside of renderMessages() (e.g., streaming)
        observeThumbnail(img);
      }

      // Click to open lightbox (only if not pending)
      img.addEventListener('click', () => {
        if (img.dataset.pending === 'true') {
          // Image still has temp ID - lightbox would fail
          return;
        }
        window.dispatchEvent(
          new CustomEvent('lightbox:open', {
            detail: {
              messageId: img.dataset.messageId,
              fileIndex: img.dataset.fileIndex,
            },
          })
        );
      });

      imgWrapper.appendChild(img);
      gallery.appendChild(imgWrapper);
    });

    container.appendChild(gallery);
  }

  // Render documents as list
  if (documents.length > 0) {
    const list = document.createElement('div');
    list.className = 'message-documents';

    documents.forEach((file) => {
      const fileIndex = files.indexOf(file);
      const doc = document.createElement('div');
      doc.className = 'message-document';
      // Make filename clickable to open in new tab (for PDFs), download button for saving
      doc.innerHTML = `
        <span class="document-icon">${getFileIcon(file.type)}</span>
        <a class="document-name document-preview"
           href="#"
           data-message-id="${file.messageId || messageId}"
           data-file-index="${file.fileIndex ?? fileIndex}"
           data-file-name="${escapeHtml(file.name)}"
           data-file-type="${file.type}"
           title="Open in new tab">${escapeHtml(file.name)}</a>
        <button class="document-download"
                data-message-id="${file.messageId || messageId}"
                data-file-index="${file.fileIndex ?? fileIndex}"
                data-file-name="${escapeHtml(file.name)}"
                title="Download">
          ${DOWNLOAD_ICON}
        </button>
      `;
      list.appendChild(doc);
    });

    container.appendChild(list);
  }

  return container;
}
