/**
 * Keyboard shortcuts for the common actions (the usual chat-app keys):
 * ⌘/Ctrl+Shift+O a new chat, ⌘/Ctrl+K the chat search, Shift+Esc the composer.
 * The buttons' tooltips and the search placeholder name them.
 */
import { getElementById } from '../utils/dom';

function withMod(e: KeyboardEvent): boolean {
  return e.metaKey || e.ctrlKey;
}

/** The shortcut's action, or null when the key is not one. */
function actionFor(e: KeyboardEvent): (() => void) | null {
  const key = e.key.toLowerCase();
  if (withMod(e) && e.shiftKey && key === 'o') {
    // the button's own handler: a chat in the open project, the sidebar closing on a phone
    return () => getElementById<HTMLButtonElement>('new-chat-btn')?.click();
  }
  if (withMod(e) && !e.shiftKey && key === 'k') {
    return () => {
      const input = getElementById<HTMLInputElement>('search-input');
      input?.focus();
      input?.select();
    };
  }
  if (e.shiftKey && !withMod(e) && key === 'escape') {
    return () => getElementById<HTMLTextAreaElement>('message-input')?.focus();
  }
  return null;
}

/** "⌘⇧O" on a Mac, "Ctrl+Shift+O" elsewhere. */
function label(shift: boolean, key: string): string {
  const mac = /Mac|iPhone|iPad/.test(navigator.platform);
  if (mac) return `⌘${shift ? '⇧' : ''}${key}`;
  return `Ctrl+${shift ? 'Shift+' : ''}${key}`;
}

/** Name the shortcuts in the tooltips of what they press. */
function addHints(): void {
  const newChat = getElementById<HTMLButtonElement>('new-chat-btn');
  if (newChat) newChat.title = `New chat (${label(true, 'O')})`;
  const search = getElementById<HTMLInputElement>('search-input');
  if (search) search.title = `Search chats (${label(false, 'K')})`;
}

export function initShortcuts(): void {
  addHints();
  document.addEventListener('keydown', (e) => {
    if (e.isComposing || e.repeat) return;
    const action = actionFor(e);
    if (!action) return;
    e.preventDefault();
    action();
  });
}
