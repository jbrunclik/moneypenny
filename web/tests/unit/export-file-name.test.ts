/**
 * The exported conversation's file name comes from Content-Disposition: the
 * UTF-8 `filename*` keeps a Czech title, `filename` is the fallback.
 */
import { describe, expect, it } from 'vitest';
import { exportFileName } from '@/api/conversations';

describe('exportFileName', () => {
  it('prefers the UTF-8 name', () => {
    const header = `attachment; filename="zadni-svetlo-2026-11-14.md"; filename*=UTF-8''Zadn%C3%AD%20sv%C4%9Btlo%202026-11-14.md`;
    expect(exportFileName(header)).toBe('Zadní světlo 2026-11-14.md');
  });

  it('falls back to the plain name, then a default', () => {
    expect(exportFileName('attachment; filename="trip-2026-11-14.md"')).toBe('trip-2026-11-14.md');
    expect(exportFileName(null)).toBe('conversation.md');
    expect(exportFileName(`attachment; filename="x.md"; filename*=UTF-8''%E0%A4%A`)).toBe('x.md');
  });
});
