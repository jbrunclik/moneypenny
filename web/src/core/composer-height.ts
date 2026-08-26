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

    // The list only needs to clear the VISIBLE composer pill, not the full
    // .input-area box - that box has a transparent gradient scrim / padding
    // above the pill (content is meant to fade THROUGH it), so measuring the
    // whole box over-clears and leaves a gap above the pill (device-verified:
    // cph=149 vs a ~87px visible pill). Measure from the pill's top edge to
    // the box bottom (= the viewport bottom, since .input-area is bottom:0).
    const pill = inputArea.querySelector<HTMLElement>('.input-container') ?? inputArea;
    const h = Math.round(
      inputArea.getBoundingClientRect().bottom - pill.getBoundingClientRect().top
    );
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
