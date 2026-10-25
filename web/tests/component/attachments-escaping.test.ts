import { describe, expect, it } from 'vitest';
import { renderMessageFiles } from '@/components/messages/attachments';
import type { FileMetadata } from '@/types/api';

// F3: every value interpolated into the document list's HTML is escaped - a
// file's MIME type and the message id come from the server, not from us
describe('document attachment markup', () => {
  const hostile = 'application/x" onmouseover="alert(1)';

  it('escapes the file type and message id', () => {
    const files = [{ name: 'a.bin', type: hostile }] as FileMetadata[];
    const container = renderMessageFiles(files, 'm1" onclick="alert(2)');
    expect(container.querySelector('[onmouseover]')).toBeNull();
    expect(container.querySelector('[onclick]')).toBeNull();
    const link = container.querySelector<HTMLElement>('.document-preview');
    expect(link?.dataset.fileType).toBe(hostile);
    expect(link?.dataset.messageId).toBe('m1" onclick="alert(2)');
  });
});
