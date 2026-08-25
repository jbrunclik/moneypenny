/**
 * Publishes the composer's live height as --composer-height on :root.
 *
 * When the composer floats over the message list (mobile liquid-glass
 * layout), the list needs bottom padding equal to the composer's height so
 * the newest message clears it, and the scroll-to-bottom button must sit
 * above it. The composer grows with multi-line input, so a static value
 * won't do - a ResizeObserver keeps the variable in sync.
 */
import { createLogger } from '../utils/logger';

const log = createLogger('composer-height');

let observer: ResizeObserver | null = null;

/** Reset for tests (prod initializes once). */
export function cleanupComposerHeight(): void {
  observer?.disconnect();
  observer = null;
  document.documentElement.style.removeProperty('--composer-height');
}

export function initComposerHeight(): void {
  const inputArea = document.querySelector<HTMLElement>('.input-area');
  if (!inputArea) return;

  const publish = (): void => {
    // offsetHeight includes padding/border - the full footprint the list
    // must clear. Round to avoid sub-pixel thrash on every keystroke.
    const h = Math.round(inputArea.getBoundingClientRect().height);
    const next = `${h}px`;
    if (document.documentElement.style.getPropertyValue('--composer-height') !== next) {
      document.documentElement.style.setProperty('--composer-height', next);
      log.debug('Composer height changed', { height: h });
    }
  };

  publish();
  if (typeof ResizeObserver === 'function') {
    observer = new ResizeObserver(publish);
    observer.observe(inputArea);
  }
}
