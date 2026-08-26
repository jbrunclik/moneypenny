/**
 * Publishes the composer's live height as --composer-height on :root.
 *
 * When the composer floats over the message list (mobile liquid-glass
 * layout), the list needs bottom padding equal to the composer's height so
 * the newest message clears it, and the scroll-to-bottom button must sit
 * above it. The composer grows with multi-line input, so a static value
 * won't do - a ResizeObserver keeps the variable in sync.
 */
import { getElementById, isScrolledToBottom } from '../utils/dom';
import { programmaticScrollToBottom } from '../utils/thumbnails';
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
    // Capture follow state BEFORE the variable (and thus the list's
    // padding-bottom) changes.
    const messages = getElementById<HTMLDivElement>('messages');
    const wasAtBottom = messages ? isScrolledToBottom(messages) : false;

    // getBoundingClientRect().height includes padding/border - the full
    // footprint the list must clear. Round to avoid sub-pixel thrash.
    const h = Math.round(inputArea.getBoundingClientRect().height);
    const next = `${h}px`;
    if (document.documentElement.style.getPropertyValue('--composer-height') !== next) {
      document.documentElement.style.setProperty('--composer-height', next);
      log.debug('Composer height changed', { height: h });

      // The list's padding-bottom is bound to --composer-height. Growing it
      // (initial measure after load, keyboard-open padding change, multi-line
      // input) pushes the newest message UP, un-pinning a bottom-scrolled
      // list and leaving a gap above the composer. Re-pin if we were
      // following the conversation.
      if (wasAtBottom && messages) {
        requestAnimationFrame(() => programmaticScrollToBottom(messages));
      }
    }
  };

  publish();
  if (typeof ResizeObserver === 'function') {
    observer = new ResizeObserver(publish);
    observer.observe(inputArea);
  }
}
