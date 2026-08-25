/**
 * Unit tests for the composer-height publisher (--composer-height).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanupComposerHeight, initComposerHeight } from '@/core/composer-height';

function getVar(): string {
  return document.documentElement.style.getPropertyValue('--composer-height');
}

describe('composer height', () => {
  let inputArea: HTMLDivElement;

  beforeEach(() => {
    document.body.innerHTML = '<div class="input-area"></div>';
    inputArea = document.querySelector('.input-area') as HTMLDivElement;
    // jsdom has no layout - stub the measured height
    vi.spyOn(inputArea, 'getBoundingClientRect').mockReturnValue({ height: 72 } as DOMRect);
  });

  afterEach(() => {
    cleanupComposerHeight();
  });

  it('publishes the composer height on init', () => {
    initComposerHeight();
    expect(getVar()).toBe('72px');
  });

  it('does nothing when there is no composer', () => {
    document.body.innerHTML = '';
    initComposerHeight();
    expect(getVar()).toBe('');
  });

  it('clears the variable on cleanup', () => {
    initComposerHeight();
    expect(getVar()).toBe('72px');
    cleanupComposerHeight();
    expect(getVar()).toBe('');
  });
});
