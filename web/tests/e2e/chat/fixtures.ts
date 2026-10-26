/**
 * Shared fixtures and utilities for chat E2E tests
 */
import type { Page } from '@playwright/test';
import { test } from '../../global-setup';
import { Buffer } from 'buffer';

/**
 * Valid PNG buffer (8x8 red image) for file upload tests
 */
export const pngBuffer = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAADklEQVQI12P4z8DAwMAAAx4D/dnaJvgAAAAASUVORK5CYII=',
  'base64'
);

/**
 * Minimal valid one-page PDF ("Hello PDF") for inline-viewer tests
 */
export const pdfBuffer = Buffer.from(
  'JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCAyMDAgMTAwXSAvQ29udGVudHMgNCAwIFIgL1Jlc291cmNlcyA8PCAvRm9udCA8PCAvRjEgNSAwIFIgPj4gPj4gPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCAzOSA+PgpzdHJlYW0KQlQgL0YxIDI0IFRmIDIwIDQwIFRkIChIZWxsbyBQREYpIFRqIEVUCmVuZHN0cmVhbQplbmRvYmoKNSAwIG9iago8PCAvVHlwZSAvRm9udCAvU3VidHlwZSAvVHlwZTEgL0Jhc2VGb250IC9IZWx2ZXRpY2EgPj4KZW5kb2JqCnhyZWYKMCA2CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAwOSAwMDAwMCBuIAowMDAwMDAwMDU4IDAwMDAwIG4gCjAwMDAwMDAxMTUgMDAwMDAgbiAKMDAwMDAwMDI0MSAwMDAwMCBuIAowMDAwMDAwMzMwIDAwMDAwIG4gCnRyYWlsZXIKPDwgL1NpemUgNiAvUm9vdCAxIDAgUiA+PgpzdGFydHhyZWYKNDAwCiUlRU9GCg==',
  'base64'
);

/**
 * Minimal 1x1 transparent PNG for lightweight tests
 */
export const pngBase64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

/**
 * Enable streaming mode
 */
/**
 * Click the Stop button. It needs force (its infinite pulse never passes the
 * stability check), so first wait until the composer has stopped MOVING: on
 * a new desktop conversation it slides down from under the welcome greeting
 * after the first send, and a forced click landed where the button had been.
 */
export async function clickStop(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const area = document.querySelector('.input-area');
    return !area || area.getAnimations().length === 0;
  });
  await page.locator('#send-btn.btn-stop').click({ timeout: 5000, force: true });
}

export async function enableStreaming(page: Page): Promise<void> {
  const streamBtn = page.locator('#stream-btn');
  const isPressed = await streamBtn.getAttribute('aria-pressed');
  if (isPressed !== 'true') {
    await streamBtn.click();
  }
}

/**
 * Disable streaming mode
 */
export async function disableStreaming(page: Page): Promise<void> {
  const streamBtn = page.locator('#stream-btn');
  const isPressed = await streamBtn.getAttribute('aria-pressed');
  if (isPressed === 'true') {
    await streamBtn.click();
  }
}

/**
 * Set stream delay for tests
 */
export async function setStreamDelay(page: Page, delayMs: number): Promise<void> {
  await page.request.post('/test/set-stream-delay', { data: { delay_ms: delayMs } });
}

/**
 * Reset stream delay to default
 */
export async function resetStreamDelay(page: Page): Promise<void> {
  await page.request.post('/test/set-stream-delay', { data: { delay_ms: 10 } });
}

/**
 * Set batch delay for tests
 */
export async function setBatchDelay(page: Page, delayMs: number): Promise<void> {
  await page.request.post('/test/set-batch-delay', { data: { delay_ms: delayMs } });
}

/**
 * Reset batch delay to default
 */
export async function resetBatchDelay(page: Page): Promise<void> {
  await page.request.post('/test/set-batch-delay', { data: { delay_ms: 0 } });
}

/**
 * Set custom mock response
 */
export async function setMockResponse(page: Page, response: string): Promise<void> {
  await page.request.post('/test/set-mock-response', { data: { response } });
}

/**
 * Clear mock response
 */
export async function clearMockResponse(page: Page): Promise<void> {
  await page.request.post('/test/clear-mock-response');
}

/**
 * Enable/disable thinking events
 */
export async function setEmitThinking(page: Page, emit: boolean): Promise<void> {
  await page.request.post('/test/set-emit-thinking', { data: { emit } });
}

/**
 * Emit a transient-error "retry" status at stream start, held for holdMs (0 = off)
 */
export async function setEmitRetry(page: Page, holdMs: number): Promise<void> {
  await page.request.post('/test/set-emit-retry', { data: { hold_ms: holdMs } });
}

/** The next streamed turn fails server-side before any text (one-shot). */
export async function failNextStream(page: Page): Promise<void> {
  await page.request.post('/test/fail-next-stream');
}

/**
 * Scroll forensics for the CI-only scroll flakes (TODO.md): records every
 * scroll write to #messages with its caller, scrollIntoView on anything inside
 * it, scroll events that no logged write explains, with the content height
 * (scroll anchoring or a layout shift), and real input. Reads
 * back with attachScrollLog. Installs into the CURRENT document as well: an
 * init script alone only arms the next navigation, which is why the old
 * inline hook never logged anything after a beforeEach goto.
 */
export async function installScrollLog(page: Page): Promise<void> {
  const hook = (): void => {
    const w = window as unknown as { __scrollLog?: string[] };
    if (w.__scrollLog) return;
    const entries: string[] = [];
    w.__scrollLog = entries;
    const t0 = performance.now();
    // A smooth-scroll animation writes every frame from one caller: fold such
    // runs into one line (count + final value) so they can't push the moment
    // that matters out of the dumped tail
    let lastKey = '';
    let runCount = 0;
    const log = (message: string, key = message): void => {
      const stamp = `${(performance.now() - t0).toFixed(0)}ms`;
      if (key === lastKey && entries.length > 0) {
        runCount += 1;
        entries[entries.length - 1] = `${stamp} (x${runCount}) ${message}`;
        return;
      }
      lastKey = key;
      runCount = 1;
      entries.push(`${stamp} ${message}`);
      if (entries.length > 300) entries.shift();
    };
    // App frames only (bundle file:line:col - minified, decode with a
    // sourcemap build of the same commit); drops this hook's own frames
    const caller = (): string =>
      (new Error().stack ?? '')
        .split('\n')
        .filter((line) => line.includes('/static/assets/'))
        .slice(0, 4)
        .map((line) => line.trim())
        .join(' | ') || '(no app frame)';
    const isList = (el: Element): boolean => el.id === 'messages';
    // Where the last logged write left the list: a scroll event there is
    // just its echo and is not logged; one anywhere else moved without a
    // logged caller (scroll anchoring, a layout shift) and is
    let landedAt: number | null = null;

    const proto = Element.prototype as unknown as Record<string, (...args: unknown[]) => void>;
    for (const name of ['scrollTo', 'scroll', 'scrollBy']) {
      const original = proto[name];
      if (!original) continue;
      proto[name] = function (this: Element, ...args: unknown[]) {
        if (isList(this)) {
          const at = caller();
          log(`${name}(${JSON.stringify(args)}) from=${Math.round(this.scrollTop)} :: ${at}`, `${name} ${at}`);
          original.apply(this, args);
          landedAt = Math.round(this.scrollTop);
          return;
        }
        return original.apply(this, args);
      };
    }
    const intoView = proto.scrollIntoView;
    if (intoView) {
      proto.scrollIntoView = function (this: Element, ...args: unknown[]) {
        if (this.closest('#messages')) {
          const at = caller();
          log(`scrollIntoView(${JSON.stringify(args)}) on ${this.tagName.toLowerCase()}.${this.className} :: ${at}`, `intoView ${at}`);
          intoView.apply(this, args);
          const list = this.closest('#messages');
          landedAt = list ? Math.round(list.scrollTop) : null;
          return;
        }
        return intoView.apply(this, args);
      };
    }
    const top = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
    if (top?.get && top.set) {
      const { get, set } = top;
      Object.defineProperty(Element.prototype, 'scrollTop', {
        get() {
          return get.call(this);
        },
        set(value: number) {
          if (isList(this as Element)) {
            const at = caller();
            log(`scrollTop=${Math.round(value)} from=${Math.round(get.call(this) as number)} :: ${at}`, `scrollTop ${at}`);
          }
          set.call(this, value);
          if (isList(this as Element)) landedAt = Math.round(get.call(this) as number);
        },
        configurable: true,
      });
    }

    document.addEventListener(
      'scroll',
      (event) => {
        const el = event.target;
        if (!(el instanceof Element) || !isList(el)) return;
        const at = Math.round(el.scrollTop);
        if (landedAt !== null && Math.abs(at - landedAt) <= 1) return;
        landedAt = at;
        log(`scroll event, no logged write landed here: top=${at} height=${el.scrollHeight} client=${el.clientHeight}`);
      },
      { capture: true, passive: true }
    );
    for (const type of ['wheel', 'touchstart', 'keydown']) {
      document.addEventListener(
        type,
        (event) => log(`input ${type}${event instanceof WheelEvent ? ` dy=${event.deltaY}` : ''}`),
        { capture: true, passive: true }
      );
    }
  };
  await page.addInitScript(hook);
  await page.evaluate(hook);
}

/** Attach the scroll log (see installScrollLog) to the test report and stdout. */
export async function attachScrollLog(page: Page, label: string): Promise<void> {
  const entries = await page.evaluate(
    () => (window as unknown as { __scrollLog?: string[] }).__scrollLog ?? ['(scroll log not installed)']
  );
  const text = `${label}\n${entries.slice(-40).join('\n')}`;
  console.log(text);
  await test.info().attach('scroll-log', { body: text, contentType: 'text/plain' });
}

// Re-export test and expect from global-setup
export { test, expect } from '../../global-setup';
