/**
 * File actions module.
 * Handles file download, preview, and clipboard operations.
 */

import { createLogger } from '../utils/logger';
import { toast } from '../components/Toast';
import { CHECK_ICON } from '../utils/icons';

const log = createLogger('file-actions');

/**
 * Open a file in a new browser tab (for preview).
 */
export async function openFileInNewTab(
  messageId: string,
  fileIndex: number,
  fileName: string,
  fileType: string
): Promise<void> {
  try {
    const { files } = await import('../api/client');
    const blob = await files.fetchFile(messageId, fileIndex);
    const url = URL.createObjectURL(blob);

    // Open in new tab
    const newTab = window.open(url, '_blank');

    // Clean up URL after a delay (give time for the tab to load)
    // For PDFs and other documents, the browser needs the URL to remain valid
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 60000); // Keep URL valid for 1 minute

    if (!newTab) {
      toast.warning('Pop-up blocked. Please allow pop-ups to preview files.');
    }
  } catch (error) {
    log.error('Failed to open file', { error, messageId, fileIndex, fileName, fileType });
    toast.error('Failed to open file.');
  }
}

/**
 * Download a file with correct filename.
 */
export async function downloadFile(messageId: string, fileIndex: number, fileName: string): Promise<void> {
  try {
    const { files } = await import('../api/client');
    const blob = await files.fetchFile(messageId, fileIndex);
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    URL.revokeObjectURL(url);
  } catch (error) {
    log.error('Failed to download file', { error, messageId, fileIndex, fileName });
    toast.error('Failed to download file.');
  }
}

/**
 * Copy message content to clipboard with rich text support.
 */
export async function copyMessageContent(button: HTMLButtonElement): Promise<void> {
  const messageEl = button.closest('.message');
  const contentEl = messageEl?.querySelector('.message-content');

  if (!contentEl) return;

  // Clone the content and remove non-response elements (files, thinking/tool traces, inline copy buttons)
  const clone = contentEl.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.message-files').forEach((el) => el.remove());
  clone.querySelectorAll('.thinking-indicator').forEach((el) => el.remove());
  clone.querySelectorAll('.inline-copy-btn').forEach((el) => el.remove());
  clone.querySelectorAll('.code-language').forEach((el) => el.remove());

  const textContent = clone.textContent?.trim();
  if (!textContent) return;

  try {
    // Copy as both plain text and HTML for rich text support
    await copyWithRichText(clone.innerHTML, textContent);
    showCopySuccess(button);
  } catch (error) {
    log.error('Failed to copy to clipboard', { error });
    toast.error('Failed to copy to clipboard.');
  }
}

/**
 * Copy inline content (code blocks, tables) to clipboard.
 */
export async function copyInlineContent(button: HTMLButtonElement): Promise<void> {
  const wrapper = button.closest('.copyable-content');
  if (!wrapper) return;

  const isCodeBlock = wrapper.classList.contains('code-block-wrapper');
  const isTable = wrapper.classList.contains('table-wrapper');

  let textContent: string;
  let htmlContent: string;

  if (isCodeBlock) {
    // For code blocks, copy plain text only (no formatting needed)
    const codeEl = wrapper.querySelector('code');
    textContent = codeEl?.textContent?.trim() || '';
    htmlContent = `<pre><code>${textContent}</code></pre>`;
  } else if (isTable) {
    // For tables, copy with HTML formatting
    const tableEl = wrapper.querySelector('table');
    if (!tableEl) return;
    textContent = tableToPlainText(tableEl);
    htmlContent = tableEl.outerHTML;
  } else {
    return;
  }

  if (!textContent) return;

  try {
    await copyWithRichText(htmlContent, textContent);
    showCopySuccess(button);
  } catch (error) {
    log.error('Failed to copy to clipboard', { error });
    toast.error('Failed to copy to clipboard.');
  }
}

/**
 * Copy content with both HTML and plain text formats.
 */
async function copyWithRichText(html: string, plainText: string): Promise<void> {
  // Try to use the modern clipboard API with multiple formats
  if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {
    try {
      const htmlBlob = new Blob([html], { type: 'text/html' });
      const textBlob = new Blob([plainText], { type: 'text/plain' });
      const clipboardItem = new ClipboardItem({
        'text/html': htmlBlob,
        'text/plain': textBlob,
      });
      await navigator.clipboard.write([clipboardItem]);
      return;
    } catch {
      // Fall back to plain text if ClipboardItem fails
    }
  }

  // Fallback to plain text only
  await navigator.clipboard.writeText(plainText);
}

/**
 * Convert table to plain text with tab-separated values.
 */
function tableToPlainText(table: HTMLTableElement): string {
  const rows: string[] = [];

  table.querySelectorAll('tr').forEach((tr) => {
    const cells: string[] = [];
    tr.querySelectorAll('th, td').forEach((cell) => {
      cells.push((cell.textContent || '').trim());
    });
    rows.push(cells.join('\t'));
  });

  return rows.join('\n');
}

/**
 * Show copy success feedback on button.
 */
function showCopySuccess(button: HTMLButtonElement): void {
  const originalHtml = button.innerHTML;
  button.innerHTML = CHECK_ICON;
  button.classList.add('copied');

  setTimeout(() => {
    button.innerHTML = originalHtml;
    button.classList.remove('copied');
  }, 2000);
}
