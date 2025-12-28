import { escapeHtml, getElementById, autoResizeTextarea, clearElement } from '../utils/dom';
import { getFileIcon, CLOSE_ICON } from '../utils/icons';
import { useStore } from '../state/store';
import type { FileUpload } from '../types/api';

/**
 * Check if running in iOS PWA mode (standalone)
 * Exported for testing
 */
export function isIOSPWA(): boolean {
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || ('standalone' in navigator && (navigator as { standalone: boolean }).standalone);
  return isIOS && isStandalone;
}

/**
 * Initialize message input handlers
 */
export function initMessageInput(onSend: () => void): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');

  if (!input || !sendBtn) return;

  // Auto-resize on input
  input.addEventListener('input', () => {
    autoResizeTextarea(input);
    updateSendButtonState();
  });

  // Send on Enter (but Shift+Enter for newline)
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  });

  // Send button click
  sendBtn.addEventListener('click', onSend);

  // iOS PWA keyboard fix: scroll the messages container when keyboard opens
  // iOS Safari in PWA mode miscalculates the scroll position when keyboard opens,
  // causing the cursor to appear below the input initially. We scroll the messages
  // container to ensure the input area is visible above the keyboard.
  if (isIOSPWA() && window.visualViewport) {
    const viewport = window.visualViewport;
    let lastHeight = viewport.height;

    const handleViewportChange = () => {
      // Only act when viewport shrinks (keyboard opening) and input is focused
      const currentHeight = viewport.height;
      const keyboardOpening = currentHeight < lastHeight;
      lastHeight = currentHeight;

      if (keyboardOpening && document.activeElement === input) {
        // Use requestAnimationFrame to wait for layout to settle
        requestAnimationFrame(() => {
          // Scroll the messages container to the bottom
          // This ensures the input stays visible above the keyboard
          const messagesContainer = document.querySelector('.messages');
          if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
          }
        });
      }
    };

    viewport.addEventListener('resize', handleViewportChange);
  }
}

/**
 * Get message input value
 */
export function getMessageInput(): string {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  return input?.value.trim() ?? '';
}

/**
 * Clear message input
 */
export function clearMessageInput(): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  if (input) {
    input.value = '';
    autoResizeTextarea(input);
    updateSendButtonState();
  }
}

/**
 * Focus message input
 */
export function focusMessageInput(): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  input?.focus();
}

/**
 * Update send button enabled state
 */
export function updateSendButtonState(): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');
  const { pendingFiles, isLoading } = useStore.getState();

  if (!sendBtn) return;

  const hasContent = (input?.value.trim().length ?? 0) > 0;
  const hasFiles = pendingFiles.length > 0;

  sendBtn.disabled = isLoading || (!hasContent && !hasFiles);
}

/**
 * Set input loading state
 */
export function setInputLoading(loading: boolean): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');

  if (input) {
    input.disabled = loading;
  }

  if (sendBtn) {
    sendBtn.disabled = loading;
    sendBtn.classList.toggle('loading', loading);
  }
}

/**
 * Render file preview area
 */
export function renderFilePreview(): void {
  const container = getElementById<HTMLDivElement>('file-preview');
  if (!container) return;

  const { pendingFiles } = useStore.getState();

  if (pendingFiles.length === 0) {
    container.classList.add('hidden');
    clearElement(container);
    return;
  }

  container.classList.remove('hidden');
  container.innerHTML = pendingFiles
    .map((file, index) => renderFilePreviewItem(file, index))
    .join('');
}

/**
 * Render a single file preview item
 */
function renderFilePreviewItem(file: FileUpload, index: number): string {
  const isImage = file.type.startsWith('image/');

  if (isImage && file.previewUrl) {
    // Image preview - just show thumbnail
    return `
      <div class="file-preview-item file-preview-image" data-index="${index}">
        <img src="${file.previewUrl}" alt="${escapeHtml(file.name)}">
        <button class="file-preview-remove" data-remove-index="${index}" aria-label="Remove file">
          ${CLOSE_ICON}
        </button>
      </div>
    `;
  }

  // Document preview - show icon and filename
  return `
    <div class="file-preview-item file-preview-doc" data-index="${index}">
      <div class="file-preview-icon">${getFileIcon(file.type)}</div>
      <span class="file-preview-name">${escapeHtml(file.name)}</span>
      <button class="file-preview-remove" data-remove-index="${index}" aria-label="Remove file">
        ${CLOSE_ICON}
      </button>
    </div>
  `;
}