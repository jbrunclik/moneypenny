/**
 * Pure helpers for the inline PDF viewer (kept separate from PdfViewer.ts
 * so they are unit-testable without pdf.js or a canvas).
 */

// Beyond this, canvases eat too much memory on mobile
const MAX_FIT_SCALE = 4;
// Rendering hundreds of pages up-front would lock up the tab; long
// documents are cut here with a "download for the rest" notice
export const MAX_RENDERED_PAGES = 100;

/** Scale a PDF page (at scale 1) to fill the container width. */
export function computeFitWidthScale(containerWidth: number, pageWidth: number): number {
  if (containerWidth <= 0 || pageWidth <= 0) return 1;
  return Math.min(MAX_FIT_SCALE, containerWidth / pageWidth);
}

/** Cap the number of rendered pages for very long documents. */
export function clampPageCount(total: number): { pages: number; truncated: boolean } {
  if (total <= MAX_RENDERED_PAGES) return { pages: total, truncated: false };
  return { pages: MAX_RENDERED_PAGES, truncated: true };
}
