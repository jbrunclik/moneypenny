/**
 * Inline PDF viewer: renders PDF attachments in a fullscreen overlay
 * instead of window.open (pop-up blockers, and broken entirely in the
 * installed PWA on iOS). pdf.js is loaded on demand - it stays out of
 * the app bundle until the first PDF is opened.
 *
 * Pages render fit-to-width into a vertically scrolling column; the
 * toolbar tracks the visible page and offers download and close.
 */
import { files } from '../api/files';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';
import { createElement } from '../utils/dom';
import { CLOSE_ICON, DOWNLOAD_ICON, setIcon, type IconHtml } from '../utils/icons';
import { downloadFile } from '../core/file-actions';
import { computeFitWidthScale, clampPageCount } from './pdf-viewer-utils';
import type { PDFPageProxy } from 'pdfjs-dist';

const log = createLogger('pdf-viewer');

const VIEWER_ID = 'pdf-viewer';

// Bumped on every open/close; async page renders from a previous session
// check it and bail instead of appending to a closed viewer
let session = 0;

export function closePdfViewer(): void {
  session++;
  document.getElementById(VIEWER_ID)?.remove();
}

registerPopupEscapeHandler(VIEWER_ID, closePdfViewer);

/** A button holding only a static icon. */
function iconButton(attributes: Record<string, string>, icon: IconHtml): HTMLButtonElement {
  const button = createElement('button', attributes);
  setIcon(button, icon);
  return button;
}

/** The viewer overlay: toolbar (title, page count, download, close) and the page column. */
function buildViewerOverlay(messageId: string, fileIndex: number, fileName: string): HTMLDivElement {
  const overlay = document.createElement('div');
  overlay.id = VIEWER_ID;
  overlay.className = 'pdf-viewer-overlay';
  overlay.append(
    createElement('div', { class: 'pdf-viewer-toolbar' }, [
      createElement('span', { class: 'pdf-viewer-title' }, [fileName]),
      createElement('span', { class: 'pdf-viewer-pages' }),
      iconButton({ class: 'pdf-viewer-download', 'aria-label': 'Download', title: 'Download' }, DOWNLOAD_ICON),
      iconButton({ class: 'pdf-viewer-close', 'aria-label': 'Close', title: 'Close' }, CLOSE_ICON),
    ]),
    createElement('div', { class: 'pdf-viewer-scroll' }, [
      createElement('div', { class: 'pdf-viewer-loading' }, ['Loading PDF...']),
    ])
  );
  overlay.querySelector('.pdf-viewer-close')?.addEventListener('click', closePdfViewer);
  overlay
    .querySelector('.pdf-viewer-download')
    ?.addEventListener('click', () => void downloadFile(messageId, fileIndex, fileName));
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closePdfViewer();
  });
  return overlay;
}

/** Render one page fit-to-width as a canvas at the device pixel ratio (capped by the caller). */
async function renderPage(
  page: PDFPageProxy,
  scroll: HTMLDivElement,
  containerWidth: number,
  dpr: number
): Promise<void> {
  const baseViewport = page.getViewport({ scale: 1 });
  const scale = computeFitWidthScale(containerWidth, baseViewport.width);
  const viewport = page.getViewport({ scale });

  const canvas = document.createElement('canvas');
  canvas.className = 'pdf-viewer-page';
  canvas.width = Math.floor(viewport.width * dpr);
  canvas.height = Math.floor(viewport.height * dpr);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  scroll.appendChild(canvas);
  await page.render({
    canvas,
    canvasContext: ctx,
    viewport,
    transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
  }).promise;
}

export async function openPdfViewer(
  messageId: string,
  fileIndex: number,
  fileName: string
): Promise<void> {
  closePdfViewer();
  const thisSession = ++session;

  const overlay = buildViewerOverlay(messageId, fileIndex, fileName);
  document.body.appendChild(overlay);

  try {
    // Lazy-load pdf.js and fetch the document in parallel
    const [pdfjs, blob] = await Promise.all([
      import('pdfjs-dist'),
      files.fetchFile(messageId, fileIndex),
    ]);
    if (thisSession !== session) return;

    const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

    const doc = await pdfjs.getDocument({ data: await blob.arrayBuffer() }).promise;
    if (thisSession !== session) return;

    const scroll = overlay.querySelector<HTMLDivElement>('.pdf-viewer-scroll');
    const pagesLabel = overlay.querySelector<HTMLSpanElement>('.pdf-viewer-pages');
    if (!scroll) return;
    scroll.innerHTML = '';

    const { pages, truncated } = clampPageCount(doc.numPages);
    if (pagesLabel) pagesLabel.textContent = `${doc.numPages} page${doc.numPages === 1 ? '' : 's'}`;

    // Account for the column's padding when fitting pages to width
    const containerWidth = Math.min(scroll.clientWidth - 24, 1200);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    for (let i = 1; i <= pages; i++) {
      const page = await doc.getPage(i);
      if (thisSession !== session) return;

      await renderPage(page, scroll, containerWidth, dpr);
    }

    if (truncated && thisSession === session) {
      const notice = document.createElement('div');
      notice.className = 'pdf-viewer-truncated';
      notice.textContent = `Showing the first ${pages} of ${doc.numPages} pages - download the file for the rest.`;
      scroll.appendChild(notice);
    }
  } catch (error) {
    log.error('Failed to render PDF', { error, messageId, fileIndex });
    if (thisSession === session) {
      closePdfViewer();
      toast.error('Failed to open the PDF.');
    }
  }
}
