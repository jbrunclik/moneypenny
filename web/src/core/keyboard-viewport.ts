/**
 * Mobile keyboard viewport pinning.
 *
 * The layout is fixed (html/body: 100vh, overflow hidden), so an on-screen
 * keyboard OVERLAYS the page instead of resizing it - the newest messages
 * and the streaming tail can hide behind the keyboard. This module measures
 * the keyboard overlap via visualViewport, exposes it as --keyboard-inset
 * (consumed by base.css to shrink the layout above the keyboard), and
 * re-pins the messages scroll to the bottom when the user was following.
 */
import { getElementById, isScrolledToBottom } from '../utils/dom';
import { programmaticScrollToBottom } from '../utils/thumbnails';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { KEYBOARD_INSET_MIN_PX } from '../config';
import { createLogger } from '../utils/logger';

const log = createLogger('keyboard-viewport');

function isEditableElement(el: Element | null): boolean {
  if (!el) return false;
  return (
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'INPUT' ||
    (el as HTMLElement).isContentEditable
  );
}

export function initKeyboardViewportPinning(): void {
  const viewport = window.visualViewport;
  if (!viewport) return; // unsupported browsers keep today's overlay behavior

  let currentInset = 0;

  const update = (): void => {
    // Pinch zoom also shrinks the visual viewport - never treat it as a
    // keyboard. Same for shrinks with no editable element focused
    // (rotations, browser chrome show/hide).
    // The overlap deliberately does NOT include viewport.offsetTop: pan
    // position churns per pixel while the user drags (welcome screen has
    // no inner scroll container, so drags pan the visual viewport), and an
    // offsetTop-dependent inset reflows the whole page mid-gesture - the
    // "extremely laggy scrolling with keyboard open" bug. Keyboard
    // GEOMETRY (innerHeight - height) is stable during pans; the focus-pan
    // that offsetTop used to compensate is reset below via scrollTo(0,0).
    const keyboardLikely = viewport.scale === 1 && isEditableElement(document.activeElement);
    const overlap = keyboardLikely
      ? Math.max(0, Math.round(window.innerHeight - viewport.height))
      : 0;
    const inset = overlap >= KEYBOARD_INSET_MIN_PX ? overlap : 0;
    if (inset === currentInset) return;
    const keyboardJustOpened = currentInset === 0 && inset > 0;

    // Capture follow state BEFORE the layout shrinks (afterwards the
    // distance-from-bottom already includes the lost height)
    const container = getElementById<HTMLDivElement>('messages');
    const wasAtBottom = container ? isScrolledToBottom(container) : false;

    currentInset = inset;
    document.documentElement.style.setProperty('--keyboard-inset', `${inset}px`);
    log.debug('Keyboard inset changed', { inset, wasAtBottom });

    if (inset > 0) {
      requestAnimationFrame(() => {
        // Standalone-PWA caret bug: iOS pans the layout viewport to reveal
        // a focused bottom input BEFORE our height shrink reflows content
        // up - WebKit then draws the caret at the stale pan position,
        // visibly outside the input. Reset the pan (the shrunk layout no
        // longer needs it) and re-assert the selection to force a redraw.
        // Only on the OPEN transition - re-running on later geometry
        // fluctuations would fight in-progress user gestures.
        if (keyboardJustOpened) {
          window.scrollTo(0, 0);
          const active = document.activeElement;
          if (
            active instanceof HTMLTextAreaElement ||
            (active instanceof HTMLInputElement && typeof active.selectionStart === 'number')
          ) {
            const { selectionStart, selectionEnd } = active;
            if (selectionStart !== null && selectionEnd !== null) {
              active.setSelectionRange(selectionStart, selectionEnd);
            }
          }
        }

        if (container && wasAtBottom) {
          // Layout has settled - keep the newest content above the keyboard
          programmaticScrollToBottom(container);
          checkScrollButtonVisibility();
        }
      });
    }
  };

  viewport.addEventListener('resize', update);
  // iOS pans the visual viewport when focusing inputs - offsetTop changes
  viewport.addEventListener('scroll', update);
  // Keyboard dismissal doesn't reliably fire a resize on iOS - re-check
  // after focus leaves the input (RAF so activeElement is already updated)
  document.addEventListener('focusout', () => requestAnimationFrame(update));
}
