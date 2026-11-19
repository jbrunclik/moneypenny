/**
 * Voice memos play in the chat (Nov 16 2026): they rendered as a plain
 * document link, so listening meant downloading. A tap fetches the file
 * (the JWT rides a header, so a bare <audio src> cannot authenticate) and
 * plays it in place; the name and download stay.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const fetchFile = vi.hoisted(() => vi.fn());
vi.mock('@/api/files', () => ({ files: { fetchFile } }));
vi.mock('@/components/messages/thumbnail-loader', () => ({ observeThumbnail: vi.fn() }));

import { renderMessageFiles } from '@/components/messages/attachments';
import type { FileMetadata } from '@/types/api';

const memo = { name: 'Memo 12.m4a', type: 'audio/x-m4a' } as FileMetadata;

beforeEach(() => {
  fetchFile.mockReset();
  URL.createObjectURL = vi.fn(() => 'blob:memo');
  HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
});

describe('audio attachments', () => {
  it('shows a play button with the name and a download, not a document link', () => {
    const el = renderMessageFiles([memo], 'm1');
    const chip = el.querySelector('.message-audio');
    expect(chip?.querySelector('button.audio-play')).not.toBeNull();
    expect(chip?.querySelector('.document-name')?.textContent).toBe('Memo 12.m4a');
    expect(chip?.querySelector('.document-download')).not.toBeNull();
    expect(chip?.querySelector('a.document-preview')).toBeNull();
  });

  it('a tap fetches the memo and plays it in place', async () => {
    fetchFile.mockResolvedValue(new Blob(['x'], { type: 'audio/mp4' }));
    const el = renderMessageFiles([memo], 'm1');
    el.querySelector<HTMLButtonElement>('button.audio-play')?.click();

    await vi.waitFor(() => expect(el.querySelector('audio.message-audio-player')).not.toBeNull());
    const audio = el.querySelector<HTMLAudioElement>('audio.message-audio-player')!;
    expect(fetchFile).toHaveBeenCalledWith('m1', 0);
    expect(audio.src).toBe('blob:memo');
    expect(audio.controls).toBe(true);
    expect(audio.play).toHaveBeenCalled();
    expect(el.querySelector('button.audio-play')).toBeNull();
  });

  it('an expired memo says so', async () => {
    fetchFile.mockRejectedValue({ status: 410 });
    const el = renderMessageFiles([memo], 'm1');
    el.querySelector<HTMLButtonElement>('button.audio-play')?.click();

    await vi.waitFor(() => expect(el.querySelector('.message-audio')?.classList.contains('expired')).toBe(true));
    expect(el.querySelector('.audio-hint')?.textContent).toMatch(/expired/i);
  });
});

describe('media blob URLs', () => {
  it('a played memo or video is released when the conversation is left', async () => {
    const { cleanupBlobUrlsForConversation } = await import('@/utils/thumbnail-blob-urls');
    const revoke = vi.fn();
    URL.revokeObjectURL = revoke;
    fetchFile.mockResolvedValue(new Blob(['x'], { type: 'audio/mp4' }));
    URL.createObjectURL = vi.fn().mockReturnValueOnce('blob:memo').mockReturnValueOnce('blob:clip');

    const el = renderMessageFiles([memo, { name: 'clip.mp4', type: 'video/mp4' } as FileMetadata], 'm1');
    el.querySelector<HTMLButtonElement>('button.audio-play')?.click();
    await vi.waitFor(() => expect(el.querySelector('audio.message-audio-player')).not.toBeNull());
    el.querySelector<HTMLButtonElement>('button.message-video-load')?.click();
    await vi.waitFor(() => expect(el.querySelector('video')).not.toBeNull());

    cleanupBlobUrlsForConversation('c1');
    expect(revoke).toHaveBeenCalledWith('blob:memo');
    expect(revoke).toHaveBeenCalledWith('blob:clip');
  });
});
