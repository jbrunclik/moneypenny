import { getElementById } from '../utils/dom';
import { useStore } from '../state/store';
import { renderFilePreview, updateSendButtonState } from './MessageInput';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import type { FileUpload } from '../types/api';

const log = createLogger('file-upload');

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

  for (const file of files) {
    // Check total file count
    if (pendingFiles.length >= uploadConfig.maxFilesPerMessage) {
      toast.warning(`Maximum ${uploadConfig.maxFilesPerMessage} files per message`);
      break;
    }

    // Check file type
    if (!uploadConfig.allowedFileTypes.includes(file.type)) {
      toast.warning(`File type '${file.type || 'unknown'}' is not allowed`);
      continue;
    }

    // Check file size
    if (file.size > uploadConfig.maxFileSize) {
      const maxMB = uploadConfig.maxFileSize / (1024 * 1024);
      toast.warning(`File '${file.name}' exceeds ${maxMB}MB limit`);
      continue;
    }

    // Convert to base64
    try {
      const data = await readFileAsBase64(file);
      const fileUpload: FileUpload = {
        name: file.name,
        type: file.type,
        data,
        previewUrl: file.type.startsWith('image/')
          ? URL.createObjectURL(file)
          : undefined,
      };

      store.addPendingFile(fileUpload);
      log.debug('File added', { fileName: file.name, fileType: file.type, fileSize: file.size });
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