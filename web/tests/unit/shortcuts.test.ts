/**
 * Keyboard shortcuts (core/shortcuts.ts): New chat, search, focus the composer.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initShortcuts } from '@/core/shortcuts';

function press(key: string, mods: Partial<Pick<KeyboardEvent, 'metaKey' | 'ctrlKey' | 'shiftKey'>> = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...mods });
  (document.activeElement ?? document.body).dispatchEvent(event);
  return event;
}

let newChat: HTMLButtonElement;
let search: HTMLInputElement;
let composer: HTMLTextAreaElement;

beforeEach(() => {
  document.body.innerHTML = `
    <button id="new-chat-btn">New Chat</button>
    <input id="search-input">
    <textarea id="message-input"></textarea>`;
  newChat = document.getElementById('new-chat-btn') as HTMLButtonElement;
  search = document.getElementById('search-input') as HTMLInputElement;
  composer = document.getElementById('message-input') as HTMLTextAreaElement;
});

initShortcuts();

describe('keyboard shortcuts', () => {
  it('⌘⇧O and Ctrl+Shift+O start a new chat', () => {
    const click = vi.spyOn(newChat, 'click');
    expect(press('o', { metaKey: true, shiftKey: true }).defaultPrevented).toBe(true);
    press('O', { ctrlKey: true, shiftKey: true });
    expect(click).toHaveBeenCalledTimes(2);
  });

  it('⌘K focuses the chat search, even from the composer', () => {
    composer.focus();
    expect(press('k', { metaKey: true }).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(search);
  });

  it('Shift+Esc focuses the composer', () => {
    search.focus();
    press('Escape', { shiftKey: true });
    expect(document.activeElement).toBe(composer);
  });

  it('names the shortcuts in the tooltips', () => {
    initShortcuts();
    expect(newChat.title).toMatch(/^New chat \((⌘⇧O|Ctrl\+Shift\+O)\)$/);
    expect(search.title).toMatch(/^Search chats \((⌘K|Ctrl\+K)\)$/);
  });

  it('leaves plain typing and other combinations alone', () => {
    const click = vi.spyOn(newChat, 'click');
    composer.focus();
    expect(press('o', { shiftKey: true }).defaultPrevented).toBe(false);
    expect(press('k').defaultPrevented).toBe(false);
    expect(press('o', { metaKey: true }).defaultPrevented).toBe(false);
    expect(click).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(composer);
  });
});
