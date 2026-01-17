import { escapeHtml, getElementById, autoResizeTextarea, clearElement } from '../utils/dom';
import { getFileIcon, CLOSE_ICON, SEND_ICON, STOP_ICON } from '../utils/icons';
import { useStore } from '../state/store';
import type { FileUpload } from '../types/api';
import { MOBILE_BREAKPOINT_PX } from '../config';
import { addFilesToPending } from './FileUpload';
import { createLogger } from '../utils/logger';

const log = createLogger('message-input');

// Track whether we're in stop mode (for click handler)
let isStopMode = false;

// Track whether input is blocked for pending approval
let isBlockedForApproval = false;

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
 * Detect any iOS/iPadOS device (including iPadOS 13+ which reports as MacIntel).
 * Exported for testing.
 */
export function isIOS(): boolean {
  const ua = navigator.userAgent;
  const isLegacyIOS = /iPad|iPhone|iPod/.test(ua);
  // iPadOS 13+ reports as MacIntel but has touch support
  const isIPadOS13Plus = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  return isLegacyIOS || isIPadOS13Plus;
}

/**
 * Should we auto-focus the input programmatically?
 * - Yes on desktop / non-iOS.
 * - No on iOS/iPad to avoid jarring keyboard/accessory bar viewport jumps.
 * Exported for testing.
 */
export function shouldAutoFocusInput(): boolean {
  return !isIOS();
}

/**
 * Check if the current viewport width is mobile-sized.
 * Uses the same breakpoint as CSS media queries (768px).
 * Exported for testing.
 */
export function isMobileViewport(): boolean {
  return window.innerWidth <= MOBILE_BREAKPOINT_PX;
}

// Store the stop callback for use in click handler
let stopCallback: (() => void) | null = null;

/**
 * Initialize message input handlers
 * @param onSend - Callback when send button is clicked (in send mode)
 * @param onStop - Callback when stop button is clicked (in stop mode)
 */
export function initMessageInput(onSend: () => void, onStop?: () => void): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');

  if (!input || !sendBtn) return;

  // Store stop callback for use in click handler
  stopCallback = onStop || null;

  // Auto-resize on input
  input.addEventListener('input', () => {
    autoResizeTextarea(input);
    updateSendButtonState();
  });

  // Send on Enter (desktop only - mobile users must tap Send button)
  // On desktop: Enter sends, Shift+Enter adds newline
  // On mobile: Enter always adds newline, must tap Send button
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !isMobileViewport()) {
      e.preventDefault();
      // Only send if not in stop mode and not blocked for approval
      if (!isStopMode && !isBlockedForApproval) {
        onSend();
      }
    }
  });

  // Send/Stop button click - behavior depends on current mode
  sendBtn.addEventListener('click', () => {
    if (isStopMode && stopCallback) {
      stopCallback();
    } else if (!isBlockedForApproval) {
      onSend();
    }
  });

  // Subscribe to streaming state changes to update button appearance
  // fireImmediately ensures we get the current state on subscription
  useStore.subscribe(
    (state) => ({
      streamingConvId: state.streamingConversationId,
      currentConvId: state.currentConversation?.id,
    }),
    ({ streamingConvId, currentConvId }) => {
      // Show stop button only when streaming the current conversation
      const shouldShowStop = streamingConvId !== null && streamingConvId === currentConvId;
      updateSendButtonMode(shouldShowStop);
    },
    {
      equalityFn: (a, b) => a.streamingConvId === b.streamingConvId && a.currentConvId === b.currentConvId,
      fireImmediately: true,
    }
  );

  // Clipboard paste handler for images
  input.addEventListener('paste', handlePaste);

  // iOS PWA keyboard fix: scroll the messages container when keyboard opens
  // iOS Safari in PWA mode miscalculates the scroll position when keyboard opens,
  // causing the cursor to appear below the input initially. We scroll the messages
  // container to ensure the input area is visible above the keyboard.
  if (isIOSPWA() && window.visualViewport) {
    const viewport = window.visualViewport;
    let lastHeight = viewport.height;
    let lastVisibilityChangeTime = 0;

    // Track visibility changes to avoid triggering on background/foreground transitions
    // When PWA goes to background and returns, visualViewport resize may fire
    document.addEventListener('visibilitychange', () => {
      lastVisibilityChangeTime = Date.now();
    });

    const handleViewportChange = () => {
      // Ignore viewport changes within 500ms of visibility change
      // This prevents false keyboard detection on background/foreground transitions
      const timeSinceVisibilityChange = Date.now() - lastVisibilityChangeTime;
      if (timeSinceVisibilityChange < 500) {
        lastHeight = viewport.height;
        return;
      }

      // Only act when viewport shrinks (keyboard opening) and input is focused
      const currentHeight = viewport.height;
      const keyboardOpening = currentHeight < lastHeight;
      lastHeight = currentHeight;

      if (keyboardOpening && document.activeElement === input) {
        // Use requestAnimationFrame to wait for layout to settle
        requestAnimationFrame(() => {
          // Scroll the messages container to the bottom
          // This ensures the input stays visible above the keyboard
          const messagesContainer = getElementById('messages');
          if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
          }
        });
      }
    };

    viewport.addEventListener('resize', handleViewportChange);
  }

  // Global keydown listener for hardware keyboard users on iOS/iPad
  // Allows typing anywhere to focus the input without needing to tap it first
  // This provides a good UX for iPad with external keyboard users while
  // still avoiding the jarring keyboard popup on conversation switch
  if (isIOS()) {
    document.addEventListener('keydown', (e) => {
      // Skip if already focused on an input/textarea/contenteditable
      const target = e.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return;
      }

      // Skip modifier-only keys and special keys
      if (
        e.key === 'Shift' ||
        e.key === 'Control' ||
        e.key === 'Alt' ||
        e.key === 'Meta' ||
        e.key === 'Escape' ||
        e.key === 'Tab' ||
        e.key === 'CapsLock' ||
        e.key === 'ArrowUp' ||
        e.key === 'ArrowDown' ||
        e.key === 'ArrowLeft' ||
        e.key === 'ArrowRight'
      ) {
        return;
      }

      // Skip if a modifier is held (except Shift for typing capitals)
      if (e.ctrlKey || e.altKey || e.metaKey) {
        return;
      }

      // Focus the input - the key event will naturally flow to it
      input.focus();
    });
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
 * Update send button enabled state (only applies in send mode, not stop mode)
 */
export function updateSendButtonState(): void {
  // Don't update enabled state while in stop mode - stop button is always enabled
  if (isStopMode) return;

  // Don't enable if blocked for approval
  if (isBlockedForApproval) return;

  const input = getElementById<HTMLTextAreaElement>('message-input');
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');
  const { pendingFiles, isLoading } = useStore.getState();

  if (!sendBtn) return;

  const hasContent = (input?.value.trim().length ?? 0) > 0;
  const hasFiles = pendingFiles.length > 0;

  sendBtn.disabled = isLoading || (!hasContent && !hasFiles);
}

/**
 * Update send button to show send or stop icon based on streaming state
 */
function updateSendButtonMode(showStop: boolean): void {
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');
  if (!sendBtn) return;

  isStopMode = showStop;

  if (showStop) {
    // Switch to stop mode
    sendBtn.innerHTML = STOP_ICON;
    sendBtn.classList.add('btn-stop');
    sendBtn.classList.remove('btn-send');
    sendBtn.title = 'Stop generating';
    sendBtn.disabled = false; // Stop button is always enabled
    log.debug('Send button switched to stop mode');
  } else {
    // Switch back to send mode
    sendBtn.innerHTML = SEND_ICON;
    sendBtn.classList.remove('btn-stop');
    sendBtn.classList.add('btn-send');
    sendBtn.title = 'Send message';
    // Re-check enabled state based on input content
    updateSendButtonState();
    log.debug('Send button switched to send mode');
  }
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
 * Set input blocked state for pending approval.
 * When blocked, shows a message overlay and disables input.
 */
export function setInputBlockedForApproval(blocked: boolean): void {
  const input = getElementById<HTMLTextAreaElement>('message-input');
  const sendBtn = getElementById<HTMLButtonElement>('send-btn');
  const inputContainer = getElementById<HTMLDivElement>('input-container');

  log.debug('setInputBlockedForApproval called', { blocked, hasInputContainer: !!inputContainer });

  // Update the flag first
  isBlockedForApproval = blocked;

  if (!inputContainer) {
    log.warn('input-container element not found');
    return;
  }

  // Check for existing overlay
  let overlay = inputContainer.querySelector<HTMLDivElement>('.approval-pending-overlay');

  if (blocked) {
    // Create overlay if it doesn't exist
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'approval-pending-overlay';
      overlay.innerHTML = `
        <span class="approval-pending-icon">⏳</span>
        <span class="approval-pending-text">Please approve or reject the pending action above</span>
      `;
      inputContainer.appendChild(overlay);
    }
    overlay.classList.remove('hidden');

    // Disable input
    if (input) {
      input.disabled = true;
      input.placeholder = 'Waiting for approval...';
    }
    if (sendBtn) {
      sendBtn.disabled = true;
    }
  } else {
    // Hide overlay
    if (overlay) {
      overlay.classList.add('hidden');
    }

    // Re-enable input (but check loading state first)
    const { isLoading } = useStore.getState();
    if (input && !isLoading) {
      input.disabled = false;
      input.placeholder = 'Ask me anything...';
    }
    // Re-check send button state
    updateSendButtonState();
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

/**
 * Show upload progress indicator
 */
export function showUploadProgress(): void {
  const container = getElementById<HTMLDivElement>('upload-progress');
  if (container) {
    container.classList.remove('hidden');
    updateUploadProgress(0);
  }
}

/**
 * Hide upload progress indicator
 */
export function hideUploadProgress(): void {
  const container = getElementById<HTMLDivElement>('upload-progress');
  if (container) {
    container.classList.add('hidden');
  }
}

/**
 * Update upload progress indicator
 * @param progress - Progress value from 0 to 100
 */
export function updateUploadProgress(progress: number): void {
  const container = getElementById<HTMLDivElement>('upload-progress');
  if (!container) return;

  const bar = container.querySelector<HTMLDivElement>('.upload-progress-bar');
  const text = container.querySelector<HTMLSpanElement>('.upload-progress-text');

  if (bar) {
    bar.style.setProperty('--progress', `${progress}%`);
  }
  if (text) {
    text.textContent = progress < 100 ? `Uploading ${progress}%` : 'Processing...';
  }
}

/**
 * Handle paste event on the message input.
 * Extracts image files from clipboard and adds them to pending files.
 * Text paste is handled normally by the browser.
 * Exported for testing.
 */
export function handlePaste(e: ClipboardEvent): void {
  const clipboardData = e.clipboardData;
  if (!clipboardData) return;

  // Extract image files from clipboard
  // Screenshots are typically provided via clipboardData.items (as DataTransferItems),
  // not clipboardData.files. We need to check items and convert them to Files.
  const imageFiles: File[] = [];

  // First, check clipboardData.items (this is where screenshots usually appear)
  if (clipboardData.items) {
    for (let i = 0; i < clipboardData.items.length; i++) {
      const item = clipboardData.items[i];
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          imageFiles.push(file);
        }
      }
    }
  }

  // Also check clipboardData.files as fallback (for drag-drop or some browsers)
  if (imageFiles.length === 0 && clipboardData.files.length > 0) {
    for (let i = 0; i < clipboardData.files.length; i++) {
      const file = clipboardData.files[i];
      if (file.type.startsWith('image/')) {
        imageFiles.push(file);
      }
    }
  }

  if (imageFiles.length === 0) {
    // No images in clipboard - let browser handle normal text paste
    return;
  }

  // Prevent default paste behavior for images
  // This stops the browser from inserting image data as text
  e.preventDefault();

  log.debug('Pasting images from clipboard', { count: imageFiles.length });

  // Generate meaningful names for pasted images
  const namedFiles = imageFiles.map((file) => {
    // Use timestamp-based name since clipboard images don't have filenames
    const extension = file.type.split('/')[1] || 'png';
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const name = `screenshot-${timestamp}.${extension}`;

    // Create a new File with the generated name
    return new File([file], name, { type: file.type });
  });

  // Add to pending files using existing upload flow
  addFilesToPending(namedFiles);
}