/**
 * File attachments rendering for messages (images, videos, and documents).
 */

import { files as filesApi } from '../../api/client';
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

  // Separate images and videos from other files
  const images = files.filter((f) => f.type.startsWith('image/'));
  const videos = files.filter((f) => f.type.startsWith('video/'));
  const documents = files.filter(
    (f) => !f.type.startsWith('image/') && !f.type.startsWith('video/')
  );

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

  // Render videos as tap-to-load players (below images, above documents visually
  // is not critical; appended after both for simplicity)
  videos.forEach((file) => {
    const fileIndex = files.indexOf(file);
    container.appendChild(
      renderVideoAttachment(file, file.messageId || messageId, file.fileIndex ?? fileIndex)
    );
  });

  return container;
}

/**
 * Render a single video attachment.
 *
 * JWT rides the Authorization header, so a bare <video src="/api/..."> cannot
 * authenticate. Playback fetches the file as a Blob via the API client and
 * plays it from an object URL. Just-uploaded videos play directly from their
 * local preview URL.
 */
function renderVideoAttachment(
  file: FileMetadata,
  messageId: string,
  fileIndex: number
): HTMLElement {
  const wrapper = document.createElement('div');
  wrapper.className = 'message-video';

  // Just-uploaded file: play directly from the local blob URL
  if (file.previewUrl) {
    wrapper.appendChild(createVideoElement(file.previewUrl));
    return wrapper;
  }

  // Historical file: click-to-load via authenticated fetch
  const button = document.createElement('button');
  button.className = 'message-video-load';

  const icon = document.createElement('span');
  icon.className = 'video-load-icon';
  icon.innerHTML = getFileIcon(file.type);

  const name = document.createElement('span');
  name.className = 'video-load-name';
  name.textContent = file.name;

  const hint = document.createElement('span');
  hint.className = 'video-load-hint';
  hint.textContent = 'Tap to load';

  button.append(icon, name, hint);

  button.addEventListener('click', () => {
    void (async () => {
      button.disabled = true;
      hint.textContent = 'Loading…';
      try {
        const blob = await filesApi.fetchFile(messageId, fileIndex);
        const video = createVideoElement(URL.createObjectURL(blob));
        wrapper.replaceChildren(video);
        void video.play();
      } catch (error) {
        const status = (error as { status?: number }).status;
        button.classList.add('expired');
        hint.textContent =
          status === 410
            ? 'Video expired (videos are kept 7 days)'
            : 'Failed to load video';
        button.disabled = status === 410;
      }
    })();
  });

  wrapper.appendChild(button);
  return wrapper;
}

function createVideoElement(src: string): HTMLVideoElement {
  const video = document.createElement('video');
  video.className = 'message-video-player';
  video.controls = true;
  video.playsInline = true;
  video.preload = 'metadata';
  video.src = src;
  return video;
}
