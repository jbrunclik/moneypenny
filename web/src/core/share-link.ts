/**
 * `#/new?text=...` opens a new chat with the text in the composer, not sent.
 *
 * iOS has no share target for a home-screen app, so a Shortcut or a bookmark
 * can open this link with selected text instead (Nov 17 2026).
 */
import { updateSendButtonState } from '../components/MessageInput';
import { autoResizeTextarea, getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { createConversation } from './conversation';

const log = createLogger('share-link');

const NEW_CHAT = '#/new';

/** The text a `#/new?text=` hash carries ('' for a bare `#/new`), or null for any other hash. */
export function sharedText(hash: string = window.location.hash): string | null {
  if (hash !== NEW_CHAT && !hash.startsWith(`${NEW_CHAT}?`)) return null;
  const query = hash.slice(NEW_CHAT.length + 1);
  return new URLSearchParams(query).get('text') ?? '';
}

/**
 * Open the link if the hash is one: a new chat, the text in the composer.
 * Returns whether it did. The hash is cleared so a reload does not repeat it.
 */
export function openSharedText(): boolean {
  const text = sharedText();
  if (text === null) return false;
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
  createConversation();
  const input = getElementById<HTMLTextAreaElement>('message-input');
  if (input && text) {
    input.value = text;
    autoResizeTextarea(input);
    updateSendButtonState();
    input.focus();
  }
  log.info('Opened a new chat from a link', { chars: text.length });
  return true;
}

/** Links opened while the app is already running. */
export function initShareLink(): void {
  window.addEventListener('hashchange', () => {
    openSharedText();
  });
}
