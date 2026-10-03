/**
 * Files on mobile: the installed iPhone app has no download manager (an
 * <a download> on a blob URL does nothing) and window.open(blob) shows a blank
 * in-app browser - so touch devices hand the file to the share sheet.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/files', () => ({
  files: { fetchFile: vi.fn(async () => new Blob(['id,name\n1,A'], { type: 'text/csv' })) },
}));
vi.mock('@/components/Toast', () => ({
  toast: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() },
  showToast: vi.fn(),
}));

import { downloadFile, openFileInNewTab } from '@/core/file-actions';
import { showToast, toast } from '@/components/Toast';

const share = vi.fn(async (_data: ShareData) => undefined);

function device(opts: { touch: boolean; standalone?: boolean; canShare?: boolean }): void {
  window.matchMedia = vi.fn((query: string) => ({
    matches:
      (query === '(pointer: coarse)' && opts.touch) ||
      (query === '(display-mode: standalone)' && Boolean(opts.standalone)),
  })) as never;
  Object.defineProperty(navigator, 'share', { value: share, configurable: true });
  Object.defineProperty(navigator, 'canShare', { value: () => opts.canShare ?? true, configurable: true });
}

function domError(name: string): DOMException {
  return new DOMException(name, name);
}

describe('mobile file download', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('hands the file to the share sheet on touch devices', async () => {
    device({ touch: true });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click');

    await downloadFile('m1', 0, 'data.csv');

    const shared = share.mock.calls[0][0].files![0];
    expect(shared.name).toBe('data.csv');
    expect(shared.type).toBe('text/csv');
    expect(click).not.toHaveBeenCalled();
  });

  it('offers a Save button when iOS refuses the share after the fetch', async () => {
    device({ touch: true });
    share.mockRejectedValueOnce(domError('NotAllowedError'));

    await downloadFile('m1', 0, 'data.csv');

    const options = vi.mocked(showToast).mock.calls[0][0];
    expect(options.action?.label).toBe('Save');
    options.action!.onClick();
    expect(share).toHaveBeenCalledTimes(2);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('says nothing when the user cancels the share sheet', async () => {
    device({ touch: true });
    share.mockRejectedValueOnce(domError('AbortError'));

    await downloadFile('m1', 0, 'data.csv');

    expect(toast.error).not.toHaveBeenCalled();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('keeps the ordinary download on desktop', async () => {
    device({ touch: false });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    await downloadFile('m1', 0, 'data.csv');

    expect(share).not.toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
  });

  it('a file name tap in the installed app shares instead of opening a blank sheet', async () => {
    device({ touch: true, standalone: true });
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);

    await openFileInNewTab('m1', 0, 'data.csv', 'text/csv');

    expect(open).not.toHaveBeenCalled();
    expect(share).toHaveBeenCalledTimes(1);
  });
});
