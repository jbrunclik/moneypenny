/**
 * Image lightbox: the gallery of one message's images (counter, prev/next,
 * arrow keys), a failed load closing with a toast, blob URLs dropped on
 * close, download, zoom toggles and the close paths.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const filesApi = vi.hoisted(() => ({ fetchFile: vi.fn() }));
const toastMock = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }));
vi.mock('@/api/files', () => ({ files: filesApi }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));

import { initLightbox } from '@/components/Lightbox';
import { mountAppShell } from '@/core/startup/app-shell';
import { initPopupEscapeListener } from '@/utils/popupEscapeHandler';

const lightbox = () => document.getElementById('lightbox')!;
const img = () => document.getElementById('lightbox-img') as HTMLImageElement;
const counter = () => document.getElementById('lightbox-counter')!.textContent;
const filename = () => document.getElementById('lightbox-filename')!.textContent;
const button = (cls: string) => lightbox().querySelector<HTMLButtonElement>(`.${cls}`)!;
const isOpen = () => !lightbox().classList.contains('hidden');

/** A message with images at the given file indexes, out of order on purpose. */
function addMessage(id: string, indexes: number[]): void {
  const message = document.createElement('div');
  message.className = 'message assistant';
  message.dataset.messageId = id;
  for (const index of indexes) {
    const image = document.createElement('img');
    image.className = 'message-image';
    image.dataset.fileIndex = String(index);
    image.alt = `photo-${index}.png`;
    message.appendChild(image);
  }
  document.getElementById('messages')!.appendChild(message);
}

async function open(messageId: string, fileIndex: number): Promise<void> {
  window.dispatchEvent(new CustomEvent('lightbox:open', { detail: { messageId, fileIndex: String(fileIndex) } }));
  await vi.waitFor(() => expect(lightbox().classList.contains('loading')).toBe(false));
}

describe('Lightbox', () => {
  let revoked: string[];

  beforeAll(() => {
    const app = document.createElement('div');
    document.body.replaceChildren(app);
    mountAppShell(app);
    initPopupEscapeListener();
    initLightbox();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    revoked = [];
    let n = 0;
    // jsdom has no blob URLs
    URL.createObjectURL = vi.fn(() => `blob:img-${++n}`);
    URL.revokeObjectURL = vi.fn((url: string) => void revoked.push(url));
    filesApi.fetchFile.mockResolvedValue(new Blob(['x']));
    document.getElementById('messages')!.replaceChildren();
    if (isOpen()) button('lightbox-close').click();
  });

  it('opens on the tapped image within its message gallery', async () => {
    addMessage('m1', [2, 0, 1]);
    await open('m1', 1);

    expect(isOpen()).toBe(true);
    expect(counter()).toBe('2 / 3');
    expect(filename()).toBe('photo-1.png');
    expect(img().src).toMatch(/^blob:/);
    expect(filesApi.fetchFile).toHaveBeenCalledWith('m1', 1);
    // Neighbours are prefetched
    await vi.waitFor(() => expect(filesApi.fetchFile).toHaveBeenCalledTimes(3));
  });

  it('navigates with the buttons and arrow keys, stopping at the ends', async () => {
    addMessage('m1', [0, 1]);
    await open('m1', 0);
    expect(button('lightbox-prev').disabled).toBe(true);

    button('lightbox-next').click();
    await vi.waitFor(() => expect(counter()).toBe('2 / 2'));
    expect(button('lightbox-next').disabled).toBe(true);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    expect(counter()).toBe('2 / 2');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
    await vi.waitFor(() => expect(counter()).toBe('1 / 2'));
  });

  it('hides navigation for a single image', async () => {
    addMessage('m1', [0]);
    await open('m1', 0);
    expect(counter()).toBe('');
    expect(button('lightbox-prev').classList.contains('hidden')).toBe(true);
    expect(button('lightbox-next').classList.contains('hidden')).toBe(true);
  });

  it('falls back to the requested file when the message is not on screen', async () => {
    await open('gone', 3);
    expect(filename()).toBe('image-3.jpg');
    expect(filesApi.fetchFile).toHaveBeenCalledWith('gone', 3);
  });

  it('closes with a toast when the image fails to load', async () => {
    addMessage('m1', [0]);
    filesApi.fetchFile.mockRejectedValue(new Error('404'));
    window.dispatchEvent(new CustomEvent('lightbox:open', { detail: { messageId: 'm1', fileIndex: '0' } }));

    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to load image.'));
    expect(isOpen()).toBe(false);
  });

  it('drops the session blob URLs on close', async () => {
    addMessage('m1', [0, 1]);
    await open('m1', 0);
    await vi.waitFor(() => expect(filesApi.fetchFile).toHaveBeenCalledTimes(2));

    button('lightbox-close').click();

    expect(isOpen()).toBe(false);
    expect(img().getAttribute('src')).toBe('');
    expect(revoked.sort()).toEqual(['blob:img-1', 'blob:img-2']);
  });

  it('downloads the shown image under its name, reusing the fetched blob', async () => {
    addMessage('m1', [0]);
    await open('m1', 0);
    const clicks: HTMLAnchorElement[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this);
    });

    button('lightbox-download').click();
    await vi.waitFor(() => expect(clicks).toHaveLength(1));

    expect(clicks[0]!.download).toBe('photo-0.png');
    expect(clicks[0]!.href).toBe('blob:img-1');
    expect(filesApi.fetchFile).toHaveBeenCalledOnce();
    click.mockRestore();
  });

  it('double-click toggles zoom; wheel zooms in and back out to fit', async () => {
    addMessage('m1', [0]);
    await open('m1', 0);

    img().dispatchEvent(new MouseEvent('dblclick', { clientX: 10, clientY: 10 }));
    expect(img().classList.contains('zoomed')).toBe(true);
    img().dispatchEvent(new MouseEvent('dblclick', { clientX: 10, clientY: 10 }));
    expect(img().classList.contains('zoomed')).toBe(false);

    img().dispatchEvent(new WheelEvent('wheel', { deltaY: -100, cancelable: true }));
    expect(img().style.transform).toContain('scale(1.2)');
    img().dispatchEvent(new WheelEvent('wheel', { deltaY: 100, cancelable: true }));
    expect(img().style.transform).toBe('');
  });

  it('closes on the backdrop and on Escape, not on the image', async () => {
    addMessage('m1', [0]);
    await open('m1', 0);
    img().click();
    expect(isOpen()).toBe(true);
    lightbox().querySelector<HTMLElement>('.lightbox-container')!.click();
    expect(isOpen()).toBe(false);

    await open('m1', 0);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(isOpen()).toBe(false);
  });
});
