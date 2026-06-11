/**
 * Single scroll listener on #messages fanning out to keyed subscribers.
 *
 * Five features independently attached scroll listeners to the same
 * container (scroll-to-bottom button, streaming auto-scroll resume,
 * older/newer message pagination, image-load scroll guard), each with its
 * own attach/cleanup bookkeeping. One passive listener now dispatches to
 * whoever is currently subscribed; subscribers keep their own debouncing.
 */
import { getElementById } from './dom';

type ScrollSubscriber = () => void;

const subscribers = new Map<string, ScrollSubscriber>();
let attachedTo: HTMLElement | null = null;

function dispatch(): void {
  // Map iteration tolerates subscribers removing themselves mid-dispatch
  for (const subscriber of subscribers.values()) {
    subscriber();
  }
}

function ensureAttached(): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container || attachedTo === container) return;
  // The container element persists across renders (only children change),
  // but guard against recreation anyway - subscribe calls re-attach
  attachedTo?.removeEventListener('scroll', dispatch);
  container.addEventListener('scroll', dispatch, { passive: true });
  attachedTo = container;
}

/**
 * Subscribe to scroll events on #messages under a unique key.
 * Re-subscribing with the same key replaces the previous subscriber.
 */
export function onMessagesScroll(key: string, subscriber: ScrollSubscriber): void {
  subscribers.set(key, subscriber);
  ensureAttached();
}

/** Remove the subscriber registered under the key (no-op if absent). */
export function offMessagesScroll(key: string): void {
  subscribers.delete(key);
}
