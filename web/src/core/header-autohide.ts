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
// Don't reveal in the bottom rubber-band zone: flinging to the bottom bounces
// back a few px, which reads as a scroll-up and popped the header in abruptly.
// At the bottom you're reading the latest content anyway, so stay hidden until
// a deliberate scroll-up moves out of this zone.
const BOTTOM_BOUNCE_ZONE_PX = 56;

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

    const distanceFromBottom = container.scrollHeight - top - container.clientHeight;

    if (top <= REVEAL_NEAR_TOP_PX) {
      setHidden(false); // always show near the top
    } else if (delta > 0) {
      setHidden(true); // scrolling down → hide
    } else if (distanceFromBottom > BOTTOM_BOUNCE_ZONE_PX) {
      setHidden(false); // deliberate scroll-up (not the bottom bounce) → reveal
    }
    lastScrollTop = top;
  });
}
