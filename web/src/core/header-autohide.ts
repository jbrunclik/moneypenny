/**
 * Auto-hide the floating mobile header while reading.
 *
 * Scrolling DOWN through a conversation slides the header up off-screen to
 * reclaim vertical space; scrolling UP (or reaching the top) brings it back so
 * the menu/title/actions are reachable. Mobile-only in effect - the CSS
 * transform is scoped to the mobile header - but the root class toggle is
 * harmless elsewhere.
 *
 * Programmatic scrolls (conversation load, scroll-to-bottom, streaming follow)
 * are ignored so the header never hides on its own; only genuine user scrolls
 * move it.
 */
import { getElementById } from '../utils/dom';
import { onMessagesScroll } from '../utils/scroll-manager';
import { isProgrammaticScrollActive } from '../utils/thumbnails';

// Keep the header while still near the top (it clears roughly its own height).
const REVEAL_NEAR_TOP_PX = 72;
// Ignore sub-pixel jitter / momentum wobble so the header doesn't flicker.
const DIRECTION_THRESHOLD_PX = 8;

let lastScrollTop = 0;

function setHidden(hidden: boolean): void {
  document.documentElement.classList.toggle('header-hidden', hidden);
}

/** Force the header visible and re-sync (call on conversation switch). */
export function revealHeader(): void {
  setHidden(false);
  const container = getElementById<HTMLDivElement>('messages');
  lastScrollTop = container?.scrollTop ?? 0;
}

export function initHeaderAutoHide(): void {
  onMessagesScroll('header-autohide', () => {
    const container = getElementById<HTMLDivElement>('messages');
    if (!container) return;

    const top = container.scrollTop;
    // Our own scrolls (load, follow, scroll-to-bottom) must never hide it.
    if (isProgrammaticScrollActive()) {
      lastScrollTop = top;
      return;
    }

    const delta = top - lastScrollTop;
    if (Math.abs(delta) < DIRECTION_THRESHOLD_PX) return;

    if (top <= REVEAL_NEAR_TOP_PX) {
      setHidden(false);
    } else {
      setHidden(delta > 0); // hide on the way down, reveal on the way up
    }
    lastScrollTop = top;
  });
}
