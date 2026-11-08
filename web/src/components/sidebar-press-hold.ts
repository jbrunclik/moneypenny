/**
 * Hold sidebar re-renders while a press on the list is in progress.
 *
 * A click fires only when the press and the release hit the same element.
 * The list re-renders by replacing every row, so a re-render between them
 * (a stream finishing retitles its row) moves the release to a new element
 * and the tap does nothing. The held render runs right after the release,
 * once the click has been dispatched.
 */
import { LIST_PRESS_RENDER_HOLD_MAX_MS } from '../config';

// UI-local (F2): the press in progress on the conversations list and the
// re-render it holds; one pointer, one list
let pressed = false;
let heldRender: (() => void) | null = null;
let capTimer: ReturnType<typeof setTimeout> | null = null;
const watchedLists = new WeakSet<HTMLElement>();
// UI-local (F2): the document release listeners are installed once
let releaseWatched = false;

function endPress(): void {
  pressed = false;
  if (capTimer !== null) clearTimeout(capTimer);
  capTimer = null;
}

/** Release or cancel: run the held render after the click is dispatched. */
function onRelease(): void {
  if (!pressed) return;
  endPress();
  const render = heldRender;
  heldRender = null;
  if (render) setTimeout(render, 0);
}

/** A release the list never heard about: stop holding. */
function onCap(): void {
  endPress();
  const render = heldRender;
  heldRender = null;
  render?.();
}

/** Start watching presses on the list (idempotent). */
export function watchListPresses(container: HTMLElement): void {
  if (!watchedLists.has(container)) {
    watchedLists.add(container);
    container.addEventListener('pointerdown', () => {
      endPress();
      pressed = true;
      capTimer = setTimeout(onCap, LIST_PRESS_RENDER_HOLD_MAX_MS);
    });
  }
  if (!releaseWatched) {
    releaseWatched = true;
    // On the document: the release may land outside the list
    document.addEventListener('pointerup', onRelease);
    document.addEventListener('pointercancel', onRelease);
  }
}

/** Returns true when a press is in progress and the render was held. */
export function holdRenderWhilePressed(render: () => void): boolean {
  if (!pressed) return false;
  heldRender = render;
  return true;
}
