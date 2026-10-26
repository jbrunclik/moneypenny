/**
 * Composer file previews: an image shows its thumbnail, a document its icon
 * and name (as text, never markup); the remove button, found by its
 * data-remove-index through the delegated handler, drops that file.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { renderFilePreview } from '@/components/MessageInput';
import { initFileUpload } from '@/components/FileUpload';
import type { FileUpload } from '@/types/api';

const preview = (): HTMLElement => document.getElementById('file-preview') as HTMLElement;

function files(): FileUpload[] {
  return [
    { name: 'photo.png', type: 'image/png', data: 'x', previewUrl: 'blob:http://localhost/1' },
    { name: '<b>notes</b>.pdf', type: 'application/pdf', data: 'y' },
  ] as FileUpload[];
}

describe('file previews', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="file-preview" class="hidden"></div>';
    URL.revokeObjectURL = vi.fn();
    useStore.setState({ pendingFiles: files() });
  });

  it('renders a thumbnail for an image and the name for a document', () => {
    renderFilePreview();
    expect(preview().classList.contains('hidden')).toBe(false);
    const [image, doc] = [...preview().querySelectorAll<HTMLElement>('.file-preview-item')];
    expect(image?.querySelector('img')?.getAttribute('src')).toBe('blob:http://localhost/1');
    expect(image?.querySelector('img')?.alt).toBe('photo.png');
    expect(doc?.querySelector('.file-preview-icon svg')).not.toBeNull();
    expect(doc?.querySelector('.file-preview-name')?.textContent).toBe('<b>notes</b>.pdf');
    expect(preview().querySelector('b')).toBeNull();
  });

  it('removes the clicked file and hides the area when none are left', () => {
    const onChanged = vi.fn(renderFilePreview);
    initFileUpload(onChanged);
    renderFilePreview();

    preview().querySelector<HTMLButtonElement>('[data-remove-index="0"]')?.click();
    expect(useStore.getState().pendingFiles.map((f) => f.name)).toEqual(['<b>notes</b>.pdf']);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/1');

    preview().querySelector<HTMLButtonElement>('[data-remove-index="0"]')?.click();
    expect(useStore.getState().pendingFiles).toEqual([]);
    expect(preview().classList.contains('hidden')).toBe(true);
  });
});
