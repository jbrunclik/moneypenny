/**
 * openPdfViewer: the overlay's toolbar, the page count and truncation
 * notice, page canvases, and closing with an error toast when the PDF
 * fails to load.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const pdf = vi.hoisted(() => ({
  getDocument: vi.fn(),
  fetchFile: vi.fn(),
  downloadFile: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: {}, getDocument: pdf.getDocument }));
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }));
vi.mock('@/api/files', () => ({ files: { fetchFile: pdf.fetchFile } }));
vi.mock('@/components/Toast', () => ({ toast: { error: pdf.toastError } }));
vi.mock('@/components/pdf-viewer-utils', () => ({
  computeFitWidthScale: () => 1,
  clampPageCount: (n: number) => ({ pages: Math.min(n, 2), truncated: n > 2 }),
}));

import { openPdfViewer } from '@/components/PdfViewer';

function fakeDoc(numPages: number) {
  const render = vi.fn(() => ({ promise: Promise.resolve() }));
  const page = { getViewport: () => ({ width: 100, height: 200 }), render };
  return { doc: { numPages, getPage: vi.fn(async () => page) }, render };
}

describe('openPdfViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
    pdf.fetchFile.mockResolvedValue({ arrayBuffer: async () => new ArrayBuffer(8) });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D);
  });

  it('renders each page and the page count, with a toolbar', async () => {
    const { doc, render } = fakeDoc(1);
    pdf.getDocument.mockReturnValue({ promise: Promise.resolve(doc) });

    await openPdfViewer('m1', 0, 'report<b>.pdf', pdf.downloadFile);

    const overlay = document.getElementById('pdf-viewer') as HTMLElement;
    expect(overlay.querySelector('.pdf-viewer-title')?.textContent).toBe('report<b>.pdf');
    expect(overlay.querySelector('.pdf-viewer-pages')?.textContent).toBe('1 page');
    expect(overlay.querySelectorAll('canvas.pdf-viewer-page')).toHaveLength(1);
    expect(overlay.querySelector('.pdf-viewer-loading')).toBeNull();
    expect(render).toHaveBeenCalledTimes(1);

    overlay.querySelector<HTMLButtonElement>('.pdf-viewer-download')?.click();
    expect(pdf.downloadFile).toHaveBeenCalledTimes(1);
    overlay.querySelector<HTMLButtonElement>('.pdf-viewer-close')?.click();
    expect(document.getElementById('pdf-viewer')).toBeNull();
  });

  it('shows the first pages of a long document with a notice', async () => {
    const { doc } = fakeDoc(5);
    pdf.getDocument.mockReturnValue({ promise: Promise.resolve(doc) });

    await openPdfViewer('m1', 0, 'long.pdf', pdf.downloadFile);

    const overlay = document.getElementById('pdf-viewer') as HTMLElement;
    expect(overlay.querySelector('.pdf-viewer-pages')?.textContent).toBe('5 pages');
    expect(overlay.querySelectorAll('canvas.pdf-viewer-page')).toHaveLength(2);
    expect(overlay.querySelector('.pdf-viewer-truncated')?.textContent).toContain('first 2 of 5 pages');
  });

  it('closes on a backdrop click', async () => {
    const { doc } = fakeDoc(1);
    pdf.getDocument.mockReturnValue({ promise: Promise.resolve(doc) });
    await openPdfViewer('m1', 0, 'a.pdf', pdf.downloadFile);

    (document.getElementById('pdf-viewer') as HTMLElement).click();
    expect(document.getElementById('pdf-viewer')).toBeNull();
  });

  it('closes and reports when the PDF cannot be loaded', async () => {
    pdf.fetchFile.mockRejectedValue(new Error('down'));

    await openPdfViewer('m1', 0, 'a.pdf', pdf.downloadFile);

    expect(document.getElementById('pdf-viewer')).toBeNull();
    expect(pdf.toastError).toHaveBeenCalledWith('Failed to open the PDF.');
  });
});
