/**
 * The startup-settled marker E2E specs wait for (core/startup/app-ready.ts).
 * When startup sets it is covered in app-startup and startup-initial-data.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { markAppReady } from '@/core/startup/app-ready';

describe('markAppReady', () => {
  afterEach(() => {
    delete document.documentElement.dataset.appReady;
  });

  it('marks <html data-app-ready>, the attribute appReady() waits for', () => {
    expect(document.documentElement.hasAttribute('data-app-ready')).toBe(false);
    markAppReady();
    expect(document.documentElement.matches('html[data-app-ready]')).toBe(true);
  });
});
