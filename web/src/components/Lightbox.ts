/**
 * Image lightbox: fullscreen-capable viewer for message images with
 * gallery navigation (all images of the same message), download,
 * double-click/double-tap zoom with drag-to-pan, swipe and arrow-key
 * navigation.
 */
import { getElementById } from '../utils/dom';
import { files } from '../api/client';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';
import { MAXIMIZE_ICON, MINIMIZE_ICON } from '../utils/icons';
import {
  computePinchScale,
  pointerDistance,
  pointerMidpoint,
  type Point,
} from './lightbox-gestures';
import {
  LIGHTBOX_SWIPE_MIN_PX,
  LIGHTBOX_ZOOM_SCALE,
  LIGHTBOX_ZOOM_MAX_SCALE,
} from '../config';

const log = createLogger('lightbox');

interface GalleryItem {
  messageId: string;
  fileIndex: number;
  name: string;
}

// Gallery session state (reset on close)
let gallery: GalleryItem[] = [];
let currentIndex = 0;
const blobUrls = new Map<string, string>();
let loadToken = 0;

// Zoom/pan state
let scale = 1;
let translateX = 0;
let translateY = 0;
// Set when a touch double-tap toggled zoom, so a browser-synthesized
// dblclick right after doesn't immediately toggle it back
let lastTouchToggleAt = 0;

function itemKey(item: GalleryItem): string {
  return `${item.messageId}:${item.fileIndex}`;
}

function isOpen(): boolean {
  return !getElementById<HTMLDivElement>('lightbox')?.classList.contains('hidden');
}

/**
 * Initialize lightbox event handlers
 */
export function initLightbox(): void {
  const lightbox = getElementById<HTMLDivElement>('lightbox');
  const img = getElementById<HTMLImageElement>('lightbox-img');
  if (!lightbox || !img) return;

  lightbox.querySelector('.lightbox-close')?.addEventListener('click', closeLightbox);
  lightbox.querySelector('.lightbox-prev')?.addEventListener('click', () => showRelative(-1));
  lightbox.querySelector('.lightbox-next')?.addEventListener('click', () => showRelative(1));
  lightbox.querySelector('.lightbox-download')?.addEventListener('click', downloadCurrent);

  // Fullscreen: not supported on iPhone Safari - hide the button there.
  // (TS types claim requestFullscreen always exists; runtime disagrees.)
  const fullscreenBtn = lightbox.querySelector<HTMLButtonElement>('.lightbox-fullscreen');
  if (fullscreenBtn) {
    if (typeof (lightbox as Partial<HTMLDivElement>).requestFullscreen === 'function') {
      fullscreenBtn.addEventListener('click', () => void toggleFullscreen(lightbox));
      document.addEventListener('fullscreenchange', () => {
        fullscreenBtn.innerHTML = document.fullscreenElement ? MINIMIZE_ICON : MAXIMIZE_ICON;
      });
    } else {
      fullscreenBtn.classList.add('hidden');
    }
  }

  // Close on backdrop click - including the non-interactive toolbar strip,
  // which is visually part of the backdrop (buttons stop propagation by
  // being the event target themselves)
  lightbox.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    if (
      target === lightbox ||
      target.classList.contains('lightbox-container') ||
      target.classList.contains('lightbox-toolbar') ||
      target.classList.contains('lightbox-meta')
    ) {
      closeLightbox();
    }
  });

  // Register with centralized Escape key handler
  registerPopupEscapeHandler('lightbox', closeLightbox);

  // Arrow-key navigation while open
  document.addEventListener('keydown', (e) => {
    if (!isOpen()) return;
    if (e.key === 'ArrowLeft') showRelative(-1);
    if (e.key === 'ArrowRight') showRelative(1);
  });

  // Double-click toggles zoom at the pointer position (desktop; touch
  // double-taps are detected manually below - iOS doesn't reliably fire
  // dblclick, and touch-action:none suppresses native gestures anyway)
  img.addEventListener('dblclick', (e) => {
    e.preventDefault();
    // Some browsers synthesize a dblclick after a touch double-tap the
    // manual detector already handled - don't toggle straight back
    if (Date.now() - lastTouchToggleAt < 500) return;
    toggleZoomAt(img, e.clientX, e.clientY);
  });

  // Wheel zoom (desktop)
  img.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      const next = Math.min(
        LIGHTBOX_ZOOM_MAX_SCALE,
        Math.max(1, scale * (e.deltaY < 0 ? 1.2 : 1 / 1.2))
      );
      if (next <= 1) {
        resetZoom(img);
      } else {
        zoomAt(img, e.clientX, e.clientY, next);
      }
    },
    { passive: false }
  );

  initTouchGestures(lightbox, img);

  // Listen for custom lightbox:open events
  window.addEventListener('lightbox:open', ((e: CustomEvent) => {
    const { messageId, fileIndex } = e.detail;
    if (messageId && fileIndex !== undefined) {
      void openLightbox(messageId, parseInt(fileIndex, 10));
    }
  }) as EventListener);
}

/**
 * Open the lightbox on a message image. All images of the same message form
 * the gallery (prev/next, swipe, arrow keys).
 */
export async function openLightbox(messageId: string, fileIndex: number): Promise<void> {
  // Collect the message's images from the DOM (they carry index + name)
  const imgs = Array.from(
    document.querySelectorAll<HTMLImageElement>(
      `.message[data-message-id="${CSS.escape(messageId)}"] img.message-image`
    )
  );
  gallery = imgs
    .map((el) => ({
      messageId,
      fileIndex: parseInt(el.dataset.fileIndex ?? '0', 10),
      name: el.alt || `image-${el.dataset.fileIndex ?? 0}.jpg`,
    }))
    .sort((a, b) => a.fileIndex - b.fileIndex);
  if (gallery.length === 0) {
    gallery = [{ messageId, fileIndex, name: `image-${fileIndex}.jpg` }];
  }

  const startIndex = gallery.findIndex((item) => item.fileIndex === fileIndex);
  getElementById<HTMLDivElement>('lightbox')?.classList.remove('hidden');
  await showIndex(startIndex >= 0 ? startIndex : 0);
}

async function getBlobUrl(item: GalleryItem): Promise<string> {
  const key = itemKey(item);
  const cached = blobUrls.get(key);
  if (cached) return cached;
  const blob = await files.fetchFile(item.messageId, item.fileIndex);
  const url = URL.createObjectURL(blob);
  blobUrls.set(key, url);
  return url;
}

async function showIndex(index: number): Promise<void> {
  const lightbox = getElementById<HTMLDivElement>('lightbox');
  const img = getElementById<HTMLImageElement>('lightbox-img');
  if (!lightbox || !img || index < 0 || index >= gallery.length) return;

  currentIndex = index;
  const item = gallery[index];
  const token = ++loadToken;

  resetZoom(img);
  updateChrome(lightbox, item);
  lightbox.classList.add('loading');
  img.src = '';

  try {
    const url = await getBlobUrl(item);
    // A newer navigation superseded this load - don't clobber it
    if (token !== loadToken) return;
    img.src = url;
    img.alt = item.name;
    lightbox.classList.remove('loading');
    prefetchNeighbors(index);
  } catch (error) {
    if (token !== loadToken) return;
    log.error('Failed to load image', { error, item });
    toast.error('Failed to load image.');
    closeLightbox();
  }
}

function showRelative(delta: number): void {
  if (!isOpen()) return;
  const next = currentIndex + delta;
  if (next < 0 || next >= gallery.length) return;
  void showIndex(next);
}

/** Warm the cache for adjacent images so navigation feels instant. */
function prefetchNeighbors(index: number): void {
  for (const neighbor of [gallery[index - 1], gallery[index + 1]]) {
    if (neighbor && !blobUrls.has(itemKey(neighbor))) {
      getBlobUrl(neighbor).catch(() => {
        // Best-effort: the real load surfaces errors if the user navigates
      });
    }
  }
}

function updateChrome(lightbox: HTMLDivElement, item: GalleryItem): void {
  const counter = getElementById<HTMLSpanElement>('lightbox-counter');
  const filename = getElementById<HTMLSpanElement>('lightbox-filename');
  if (counter) {
    counter.textContent = gallery.length > 1 ? `${currentIndex + 1} / ${gallery.length}` : '';
  }
  if (filename) {
    filename.textContent = item.name;
  }
  const prev = lightbox.querySelector<HTMLButtonElement>('.lightbox-prev');
  const next = lightbox.querySelector<HTMLButtonElement>('.lightbox-next');
  const multi = gallery.length > 1;
  if (prev) {
    prev.classList.toggle('hidden', !multi);
    prev.disabled = currentIndex === 0;
  }
  if (next) {
    next.classList.toggle('hidden', !multi);
    next.disabled = currentIndex === gallery.length - 1;
  }
}

function downloadCurrent(): void {
  const item = gallery[currentIndex];
  if (!item) return;
  // The blob is already fetched for display - reuse it
  getBlobUrl(item)
    .then((url) => {
      const a = document.createElement('a');
      a.href = url;
      a.download = item.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    })
    .catch((error: unknown) => {
      log.error('Failed to download image', { error, item });
      toast.error('Failed to download image.');
    });
}

async function toggleFullscreen(lightbox: HTMLDivElement): Promise<void> {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await lightbox.requestFullscreen();
    }
  } catch (error) {
    log.warn('Fullscreen toggle failed', { error });
  }
}

// ============ Zoom / pan ============

function applyTransform(img: HTMLImageElement): void {
  img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
}

function resetZoom(img: HTMLImageElement): void {
  scale = 1;
  translateX = 0;
  translateY = 0;
  img.style.transform = '';
  img.classList.remove('zoomed');
}

function toggleZoomAt(img: HTMLImageElement, clientX: number, clientY: number): void {
  if (scale > 1) {
    resetZoom(img);
  } else {
    zoomAt(img, clientX, clientY, LIGHTBOX_ZOOM_SCALE);
  }
}

/**
 * Touch gestures: pinch zoom (two-pointer distance ratio anchored at the
 * midpoint), one-finger pan while zoomed, manual double-tap zoom toggle,
 * and swipe navigation when not zoomed. Pointer events cover pinch/pan/tap;
 * touch events handle the swipe so it also works starting on the backdrop.
 */
function initTouchGestures(lightbox: HTMLDivElement, img: HTMLImageElement): void {
  const activePointers = new Map<number, Point>();
  let pinchStartDistance = 0;
  let pinchStartScale = 1;
  let gestureHadPinch = false;
  let downPosition: Point | null = null;
  let lastTapAt = 0;
  let lastTapPosition: Point | null = null;

  img.addEventListener('pointerdown', (e) => {
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    img.setPointerCapture(e.pointerId);
    if (activePointers.size === 1) {
      downPosition = { x: e.clientX, y: e.clientY };
    } else if (activePointers.size === 2) {
      const [a, b] = [...activePointers.values()];
      pinchStartDistance = pointerDistance(a, b);
      pinchStartScale = scale;
      gestureHadPinch = true;
    }
  });

  img.addEventListener('pointermove', (e) => {
    const previous = activePointers.get(e.pointerId);
    if (!previous) return;
    const current = { x: e.clientX, y: e.clientY };
    activePointers.set(e.pointerId, current);

    if (activePointers.size === 2 && pinchStartDistance > 0) {
      const [a, b] = [...activePointers.values()];
      const midpoint = pointerMidpoint(a, b);
      const next = computePinchScale(pinchStartScale, pinchStartDistance, pointerDistance(a, b));
      if (next <= 1.02) {
        resetZoom(img);
      } else {
        zoomAt(img, midpoint.x, midpoint.y, next);
      }
    } else if (activePointers.size === 1 && scale > 1) {
      translateX += current.x - previous.x;
      translateY += current.y - previous.y;
      clampPan(img);
      applyTransform(img);
    }
  });

  const releasePointer = (e: PointerEvent): void => {
    activePointers.delete(e.pointerId);
    if (activePointers.size < 2) {
      pinchStartDistance = 0;
    }
    if (activePointers.size > 0) return;

    // Gesture over: detect touch double-taps (iOS doesn't reliably fire
    // dblclick, and the global viewport meta disables native double-tap)
    if (e.pointerType === 'touch' && e.type === 'pointerup' && !gestureHadPinch && downPosition) {
      const movedPx = pointerDistance(downPosition, { x: e.clientX, y: e.clientY });
      const isTap = movedPx < 10;
      const now = Date.now();
      if (
        isTap &&
        now - lastTapAt < 300 &&
        lastTapPosition &&
        pointerDistance(lastTapPosition, { x: e.clientX, y: e.clientY }) < 40
      ) {
        toggleZoomAt(img, e.clientX, e.clientY);
        lastTouchToggleAt = now;
        lastTapAt = 0;
        lastTapPosition = null;
      } else if (isTap) {
        lastTapAt = now;
        lastTapPosition = { x: e.clientX, y: e.clientY };
      }
    }
    gestureHadPinch = false;
    downPosition = null;
  };
  img.addEventListener('pointerup', releasePointer);
  img.addEventListener('pointercancel', releasePointer);

  // Swipe navigation (only when not zoomed - zoomed touches pan instead)
  let touchStart: Point | null = null;
  let touchGestureHadPinch = false;
  lightbox.addEventListener(
    'touchstart',
    (e) => {
      if (e.touches.length === 1) {
        touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        touchGestureHadPinch = false;
      } else {
        touchGestureHadPinch = true;
      }
    },
    { passive: true }
  );
  lightbox.addEventListener(
    'touchend',
    (e) => {
      if (scale > 1 || touchGestureHadPinch || !touchStart || e.touches.length > 0) return;
      const dx = e.changedTouches[0].clientX - touchStart.x;
      const dy = e.changedTouches[0].clientY - touchStart.y;
      if (Math.abs(dx) > LIGHTBOX_SWIPE_MIN_PX && Math.abs(dx) > Math.abs(dy) * 1.5) {
        showRelative(dx < 0 ? 1 : -1);
      }
    },
    { passive: true }
  );
}

function zoomAt(img: HTMLImageElement, clientX: number, clientY: number, newScale: number): void {
  const rect = img.getBoundingClientRect();
  // Keep the point under the cursor stationary while scaling
  const offsetX = clientX - (rect.left + rect.width / 2);
  const offsetY = clientY - (rect.top + rect.height / 2);
  const ratio = newScale / scale;
  translateX = translateX * ratio - offsetX * (ratio - 1);
  translateY = translateY * ratio - offsetY * (ratio - 1);
  scale = newScale;
  clampPan(img);
  applyTransform(img);
  img.classList.add('zoomed');
}

/** Keep at least part of the image on screen while panning. */
function clampPan(img: HTMLImageElement): void {
  const maxX = ((scale - 1) * img.clientWidth) / 2;
  const maxY = ((scale - 1) * img.clientHeight) / 2;
  translateX = Math.min(maxX, Math.max(-maxX, translateX));
  translateY = Math.min(maxY, Math.max(-maxY, translateY));
}

/**
 * Close lightbox
 */
export function closeLightbox(): void {
  const lightbox = getElementById<HTMLDivElement>('lightbox');
  const img = getElementById<HTMLImageElement>('lightbox-img');

  if (document.fullscreenElement) {
    void document.exitFullscreen().catch(() => undefined);
  }

  if (lightbox) {
    lightbox.classList.add('hidden');
    lightbox.classList.remove('loading');
  }

  if (img) {
    img.src = '';
    resetZoom(img);
  }

  // Invalidate any in-flight load and drop the session's blob URLs
  loadToken++;
  for (const url of blobUrls.values()) {
    URL.revokeObjectURL(url);
  }
  blobUrls.clear();
  gallery = [];
  currentIndex = 0;
}
