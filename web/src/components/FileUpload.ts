import { getElementById } from '../utils/dom';
import { useStore } from '../state/store';
import { renderFilePreview, updateSendButtonState } from './MessageInput';
import { toast, showToast, dismissToast } from './Toast';
import { createLogger } from '../utils/logger';
import { compressImageFile } from '../utils/image-compression';
import { transcodeVideoFile } from '../utils/video-transcode';
import type { FileUpload, UploadConfig } from '../types/api';

const log = createLogger('file-upload');

/** Per-type upload size limit (videos get a larger allowance) */
export function maxSizeForType(config: UploadConfig, mimeType: string): number {
  return mimeType.startsWith('video/') ? config.maxVideoFileSize : config.maxFileSize;
}

// Extensions whose MIME type browsers often fail to report (empty or
// octet-stream) - notably HEIC from Windows/Linux pickers and some
// Android browsers, where the extension is the only signal
const EXTENSION_MIME_FALLBACKS: Record<string, string> = {
  heic: 'image/heic',
  heif: 'image/heif',
};

/**
 * Transcode a large video with a persistent progress toast. The toast is
 * pure feedback - the transcode itself fails open to the original file.
 */
function formatMB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function transcodeVideoWithToast(file: File): Promise<File> {
  let toastId: string | null = null;
  try {
    const result = await transcodeVideoFile(file, (fraction) => {
      // Create the toast lazily on first progress (small/unsupported
      // videos resolve without ever reporting), then patch the message
      // in place - dismiss+recreate would flicker on every tick
      if (!toastId) {
        toastId = showToast({ type: 'info', message: 'Compressing video…', duration: 0 });
      }
      const messageEl = document.querySelector(
        `[data-toast-id="${toastId}"] .toast-message`
      );
      if (messageEl) {
        messageEl.textContent = `Compressing video… ${Math.round(fraction * 100)}%`;
      }
    });
    // Make the outcome visible - the progress toast disappears quickly
    // and console logs are impractical on mobile
    if (result !== file) {
      toast.success(`Video compressed: ${formatMB(file.size)} → ${formatMB(result.size)}`);
    }
    return result;
  } finally {
    if (toastId) dismissToast(toastId);
  }
}

/**
 * Resolve a file's MIME type, falling back to the extension when the
 * browser reports none. A concrete declared type is always trusted.
 */
export function resolveFileType(file: File): string {
  if (file.type && file.type !== 'application/octet-stream') {
    return file.type;
  }
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  return EXTENSION_MIME_FALLBACKS[ext] ?? file.type;
}

/**
 * Initialize file upload handlers
 */
export function initFileUpload(): void {
  const attachBtn = getElementById<HTMLButtonElement>('attach-btn');
  const fileInput = getElementById<HTMLInputElement>('file-input');
  const filePreview = getElementById<HTMLDivElement>('file-preview');
  const dropZone = document.querySelector<HTMLDivElement>('.input-area');

  // Attach button click
  attachBtn?.addEventListener('click', () => {
    fileInput?.click();
  });

  // File input change
  fileInput?.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length > 0) {
      addFilesToPending(Array.from(fileInput.files));
      fileInput.value = ''; // Reset for next selection
    }
  });

  // File preview remove buttons (event delegation)
  filePreview?.addEventListener('click', (e) => {
    const removeBtn = (e.target as HTMLElement).closest('[data-remove-index]');
    if (removeBtn) {
      const index = parseInt(
        (removeBtn as HTMLElement).dataset.removeIndex!,
        10
      );
      removeFile(index);
    }
  });

  // Drag and drop
  if (dropZone) {
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('drag-over');

      const files = Array.from(e.dataTransfer?.files || []);
      if (files.length > 0) {
        addFilesToPending(files);
      }
    });
  }
}

/**
 * Add files to pending upload queue
 * Exported for use by clipboard paste handler
 */
export async function addFilesToPending(files: File[]): Promise<void> {
  log.debug('Processing files for upload', { count: files.length });
  const store = useStore.getState();
  const { uploadConfig, pendingFiles } = store;

  for (let file of files) {
    // Check total file count
    if (pendingFiles.length >= uploadConfig.maxFilesPerMessage) {
      toast.warning(`Maximum ${uploadConfig.maxFilesPerMessage} files per message`);
      break;
    }

    // Resolve missing/generic MIME types by extension (e.g. HEIC from
    // Windows pickers arrives as octet-stream); re-wrap so the corrected
    // type flows through compression, size checks and the upload payload
    const resolvedType = resolveFileType(file);
    if (resolvedType !== file.type) {
      file = new File([file], file.name, { type: resolvedType });
    }

    // Check file type
    if (!uploadConfig.allowedFileTypes.includes(file.type)) {
      toast.warning(`File type '${file.type || 'unknown'}' is not allowed`);
      continue;
    }

    // Compress images client-side (full-res photos waste upload, storage and
    // LLM tokens). Runs before the size check so an oversized photo that
    // compresses under the limit is still accepted. Falls back to the
    // original file on any decode/encode problem.
    try {
      let processed = await compressImageFile(file);

      // Large videos: transcode to ~720p H.264 MP4 so uploads survive slow
      // connections. Fail-open (returns the original when unsupported);
      // small videos are skipped inside transcodeVideoFile
      if (processed.type.startsWith('video/')) {
        processed = await transcodeVideoWithToast(processed);
      }

      // Check file size (per-type limit: videos get a larger allowance)
      const maxSize = maxSizeForType(uploadConfig, processed.type);
      if (processed.size > maxSize) {
        const maxMB = maxSize / (1024 * 1024);
        toast.warning(`File '${file.name}' exceeds ${maxMB}MB limit`);
        continue;
      }

      const data = await readFileAsBase64(processed);
      const fileUpload: FileUpload = {
        name: processed.name,
        type: processed.type,
        data,
        previewUrl:
          processed.type.startsWith('image/') || processed.type.startsWith('video/')
            ? URL.createObjectURL(processed)
            : undefined,
      };

      store.addPendingFile(fileUpload);
      log.debug('File added', {
        fileName: processed.name,
        fileType: processed.type,
        fileSize: processed.size,
        originalSize: file.size,
      });
    } catch (error) {
      log.error('Failed to read file', { error, fileName: file.name });
      toast.error(`Failed to read file '${file.name}'`);
    }
  }

  renderFilePreview();
  updateSendButtonState();
}

/**
 * Remove file from pending queue
 */
function removeFile(index: number): void {
  const store = useStore.getState();
  const file = store.pendingFiles[index];

  // Revoke blob URL if present
  if (file?.previewUrl) {
    URL.revokeObjectURL(file.previewUrl);
  }

  store.removePendingFile(index);
  renderFilePreview();
  updateSendButtonState();
}

/**
 * Clear all pending files
 */
export function clearPendingFiles(): void {
  const store = useStore.getState();

  // Revoke all blob URLs
  store.pendingFiles.forEach((file) => {
    if (file.previewUrl) {
      URL.revokeObjectURL(file.previewUrl);
    }
  });

  store.clearPendingFiles();
  renderFilePreview();
  updateSendButtonState();
}

/**
 * Get pending files for sending
 */
export function getPendingFiles(): FileUpload[] {
  return useStore.getState().pendingFiles;
}

/**
 * Read file as base64 string
 */
function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Remove data URL prefix (e.g., "data:image/png;base64,")
      const base64 = result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}