/** Text size (Settings > Appearance): a per-device scale on <html>. */
import { describe, it, expect, beforeEach } from 'vitest';
import { applyTextSize, getTextSize, setTextSize } from '@/utils/preferences';

describe('text size', () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.textSize;
  });

  it('defaults to the normal size, with no attribute', () => {
    applyTextSize();
    expect(getTextSize()).toBe('default');
    expect(document.documentElement.dataset.textSize).toBeUndefined();
  });

  it('saves and applies a larger size, and back', () => {
    setTextSize('larger');
    expect(getTextSize()).toBe('larger');
    expect(document.documentElement.dataset.textSize).toBe('larger');
    setTextSize('default');
    expect(document.documentElement.dataset.textSize).toBeUndefined();
  });

  it('ignores an unknown stored value', () => {
    localStorage.setItem('text_size', 'tiny');
    expect(getTextSize()).toBe('default');
  });
});
