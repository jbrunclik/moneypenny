/**
 * Image attachments: a local preview, a lazily fetched thumbnail, or a
 * filename placeholder for an unconfirmed send; the lightbox opens only
 * for images the server has.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const observeThumbnail = vi.hoisted(() => vi.fn());
vi.mock('@/components/messages/thumbnail-loader', () => ({ observeThumbnail }));

import { renderMessageFiles } from '@/components/messages/attachments';
import type { FileMetadata } from '@/types/api';

const image = (extra: Partial<FileMetadata> = {}): FileMetadata =>
  ({ name: 'cat.jpg', type: 'image/jpeg', ...extra }) as FileMetadata;

describe('message image attachments', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a local preview directly', () => {
    const el = renderMessageFiles([image({ previewUrl: 'blob:local' })], 'm1');
    const img = el.querySelector<HTMLImageElement>('.message-images img.message-image');
    expect(img?.getAttribute('src')).toBe('blob:local');
    expect(img?.closest('.message-image-wrapper')?.classList.contains('loading')).toBe(false);
    expect(observeThumbnail).not.toHaveBeenCalled();
  });

  it('lazy-loads a server thumbnail behind a filename placeholder', () => {
    const el = renderMessageFiles([image()], 'm1');
    const img = el.querySelector<HTMLImageElement>('img.message-image') as HTMLImageElement;
    const wrapper = img.closest('.message-image-wrapper') as HTMLElement;
    expect(wrapper.classList.contains('loading')).toBe(true);
    expect(wrapper.querySelector('.image-placeholder')?.textContent).toBe('cat.jpg');
    expect(img.loading).toBe('lazy');
    expect(observeThumbnail).toHaveBeenCalledWith(img);

    img.dispatchEvent(new Event('load'));
    expect(wrapper.classList.contains('loading')).toBe(false);
  });

  it('opens the lightbox with the message and file index', () => {
    const files = [{ name: 'a.pdf', type: 'application/pdf' } as FileMetadata, image()];
    const el = renderMessageFiles(files, 'm1');
    const handler = vi.fn();
    window.addEventListener('lightbox:open', handler);

    el.querySelector<HTMLImageElement>('img.message-image')?.click();

    window.removeEventListener('lightbox:open', handler);
    expect((handler.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({ messageId: 'm1', fileIndex: '1' });
  });

  it('prefers the file\'s own message id and index', () => {
    const el = renderMessageFiles([image({ messageId: 'm9', fileIndex: 4 })], 'm1');
    const img = el.querySelector<HTMLImageElement>('img.message-image') as HTMLImageElement;
    expect(img.dataset.messageId).toBe('m9');
    expect(img.dataset.fileIndex).toBe('4');
  });

  it('keeps an unconfirmed send without a preview as a placeholder, lightbox off', () => {
    const el = renderMessageFiles([image()], 'temp-1', true);
    const img = el.querySelector<HTMLImageElement>('img.message-image') as HTMLImageElement;
    expect(img.dataset.pending).toBe('true');
    expect(img.closest('.message-image-wrapper')?.querySelector('.image-placeholder')).not.toBeNull();
    expect(observeThumbnail).not.toHaveBeenCalled();

    const handler = vi.fn();
    window.addEventListener('lightbox:open', handler);
    img.click();
    window.removeEventListener('lightbox:open', handler);
    expect(handler).not.toHaveBeenCalled();
  });
});
