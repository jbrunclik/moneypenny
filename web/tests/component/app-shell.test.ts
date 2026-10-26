/**
 * The app shell (core/startup/app-shell.ts): the static markup every view
 * renders into, and the boot loader for a deep-linked route.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/messages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/components/messages')>()),
  showConversationLoader: vi.fn(() => {
    const loader = document.createElement('div');
    loader.className = 'conversation-loader';
    document.getElementById('messages')?.appendChild(loader);
  }),
}));

import { mountAppShell } from '@/core/startup/app-shell';

// Elements other modules look up by id at init
const REQUIRED_IDS = [
  'sidebar',
  'new-chat-btn',
  'search-container',
  'conversations-list',
  'user-info',
  'menu-btn',
  'current-chat-title',
  'chat-header',
  'messages',
  'message-input',
  'send-btn',
  'stream-btn',
  'attach-btn',
  'file-input',
  'model-selector-btn',
  'model-dropdown',
  'lightbox',
  'lightbox-img',
  'sources-popup',
  'settings-popup',
  'login-overlay',
  'google-login-btn',
];

let app: HTMLDivElement;

beforeEach(() => {
  app = document.createElement('div');
  app.id = 'app';
  document.body.appendChild(app);
});

afterEach(() => {
  app.remove();
  window.location.hash = '';
});

describe('mountAppShell', () => {
  it('renders every element the views look up, once', () => {
    mountAppShell(app);
    for (const id of REQUIRED_IDS) {
      expect(document.querySelectorAll(`#${id}`), id).toHaveLength(1);
    }
    const ids = [...app.querySelectorAll('[id]')].map((el) => el.id);
    expect(ids.filter((id, i) => ids.indexOf(id) !== i)).toEqual([]);
  });

  it('starts with sending disabled, streaming on and the login overlay hidden', () => {
    mountAppShell(app);
    expect(document.getElementById('send-btn')?.hasAttribute('disabled')).toBe(true);
    expect(document.getElementById('stream-btn')?.getAttribute('aria-pressed')).toBe('true');
    expect(document.getElementById('login-overlay')?.classList.contains('hidden')).toBe(true);
  });

  it('greets with the welcome screen on the home route', () => {
    mountAppShell(app);
    const messages = document.getElementById('messages')!;
    expect(messages.children.length).toBeGreaterThan(0);
    expect(messages.querySelector('.conversation-loader')).toBeNull();
  });

  it('shows a loader instead when booting into a conversation', () => {
    window.location.hash = '#/conversations/abc';
    mountAppShell(app);
    const messages = document.getElementById('messages')!;
    expect(messages.children).toHaveLength(1);
    expect(messages.querySelector('.conversation-loader')).not.toBeNull();
  });

  it('replaces what was mounted before', () => {
    mountAppShell(app);
    mountAppShell(app);
    expect(document.querySelectorAll('#messages')).toHaveLength(1);
  });
});
