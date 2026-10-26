/**
 * The app shell: the static markup every view renders into, and mounting it.
 */
import { createWelcomeMessage } from '../../components/WelcomeMessage';
import { showConversationLoader } from '../../components/messages';
import { createCostHistoryPopupShell } from '../../components/CostHistoryPopup';
import { createCompactionPopupShell } from '../../components/CompactionIndicator';
import { createPopupShell } from '../../components/InfoPopup';
import { APP_NAME } from '../../config';
import { createElement, getElementById, clearElement } from '../../utils/dom';
import { parseHash } from '../../router/deeplink';
import {
  ATTACH_ICON,
  CHEVRON_DOWN_ICON,
  CHEVRON_LEFT_ICON,
  CHEVRON_RIGHT_ICON,
  SLIDERS_ICON,
  CLOSE_ICON,
  DOWNLOAD_ICON,
  MAXIMIZE_ICON,
  SEND_ICON,
  MICROPHONE_ICON,
  STREAM_ICON,
  SEARCH_ICON,
  SPARKLES_ICON,
  PLUS_ICON,
  INCOGNITO_ICON,
  MENU_ICON,
  DELETE_ICON,
  createIconButton,
  createIconElement,
  iconNodes,
  type IconHtml,
} from '../../utils/icons';

const el = createElement;

/** A button: its icon, then its text label. */
function iconTextButton(attributes: Record<string, string>, icon: IconHtml, label: string): HTMLButtonElement {
  return el('button', attributes, [iconNodes(icon), label]);
}

/** The sidebar: brand, New Chat, selection bar, search, list, user info. */
function sidebar(): HTMLElement {
  return el('aside', { id: 'sidebar', class: 'sidebar' }, [
    el('div', { class: 'sidebar-header' }, [
      el('div', { class: 'sidebar-brand' }, [
        el('img', { class: 'sidebar-logo', src: '/static/icon-192.png', alt: '', width: '28', height: '28' }),
        el('h1', {}, [APP_NAME]),
      ]),
      iconTextButton({ id: 'new-chat-btn', class: 'btn btn-primary btn-new-chat' }, PLUS_ICON, ' New Chat'),
    ]),
    el('div', { id: 'selection-bar', class: 'selection-bar hidden', role: 'toolbar', 'aria-label': 'Select chats' }, [
      el('button', { id: 'selection-cancel', type: 'button', class: 'selection-bar-btn' }, ['Cancel']),
      el('span', { class: 'selection-count', 'aria-live': 'polite' }, ['0 selected']),
      el('button', { id: 'selection-all', type: 'button', class: 'selection-bar-btn' }, ['Select all']),
    ]),
    el('div', { id: 'search-container', class: 'search-container' }),
    el('div', { id: 'conversations-list', class: 'conversations-list' }),
    el('div', { class: 'sidebar-footer' }, [el('div', { id: 'user-info', class: 'user-info' })]),
    el('div', { id: 'selection-footer', class: 'selection-footer hidden' }, [
      iconTextButton({ id: 'selection-trash', type: 'button', class: 'btn btn-primary', disabled: '' }, DELETE_ICON, ' Move 0 to trash'),
    ]),
  ]);
}

/** A composer toggle: icon and label, pressed state in aria-pressed. */
function toolbarToggle(id: string, icon: IconHtml, label: string, title: string, ariaLabel: string, pressed = false): HTMLButtonElement {
  return el('button', { id, class: `btn-toolbar${pressed ? ' active' : ''}`, title, 'aria-label': ariaLabel, 'aria-pressed': String(pressed) }, [
    iconNodes(icon),
    el('span', { class: 'toolbar-toggle-label' }, [label]),
  ]);
}

/** The composer's toolbar: model, toggles, voice, attach, send. */
function composerToolbar(): HTMLElement {
  return el('div', { class: 'input-toolbar' }, [
    el('div', { class: 'toolbar-left' }, [
      el('div', { class: 'model-selector' }, [
        el('button', { id: 'model-selector-btn', class: 'model-selector-btn' }, [
          el('span', { id: 'current-model-name' }, ['Loading...']),
          createIconElement('dropdown-arrow', CHEVRON_DOWN_ICON),
        ]),
        el('div', { id: 'model-dropdown', class: 'model-dropdown hidden' }),
      ]),
      createIconButton(
        { id: 'toolbar-options-btn', class: 'btn-toolbar', 'aria-label': 'Message options', 'aria-expanded': 'false' },
        SLIDERS_ICON
      ),
      el('div', { class: 'toolbar-toggles' }, [
        toolbarToggle('stream-btn', STREAM_ICON, 'Streaming', 'Toggle streaming', 'Toggle streaming', true),
        toolbarToggle('search-btn', SEARCH_ICON, 'Web search', 'Force web search for next message', 'Force web search for next message'),
        toolbarToggle(
          'imagegen-btn',
          SPARKLES_ICON,
          'Generate image',
          'Force image generation for next message',
          'Force image generation for next message'
        ),
        toolbarToggle(
          'anonymous-btn',
          INCOGNITO_ICON,
          'Incognito',
          'Anonymous mode - disable memory and integrations',
          'Anonymous mode'
        ),
      ]),
    ]),
    el('div', { class: 'toolbar-right' }, [
      createIconButton(
        { id: 'voice-btn', class: 'btn-toolbar btn-voice', title: 'Voice input', 'aria-label': 'Voice input', 'aria-pressed': 'false' },
        MICROPHONE_ICON
      ),
      createIconButton({ id: 'attach-btn', class: 'btn-toolbar', title: 'Attach files', 'aria-label': 'Attach files' }, ATTACH_ICON),
      createIconButton({ id: 'send-btn', class: 'btn btn-send', 'aria-label': 'Send message', disabled: '' }, SEND_ICON),
    ]),
  ]);
}

/** The input area at the bottom of the chat. */
function composer(): HTMLElement {
  return el('div', { class: 'input-area' }, [
    el('div', { class: 'input-wrapper' }, [
      el('div', { id: 'file-preview', class: 'file-preview hidden' }),
      el('input', {
        type: 'file',
        id: 'file-input',
        multiple: '',
        accept: 'image/*,video/mp4,video/quicktime,video/webm,application/pdf,text/plain,text/markdown,text/csv,application/json',
      }),
      el('div', { id: 'input-container', class: 'input-container' }, [
        el('div', { id: 'quick-actions-bar', class: 'quick-actions-bar hidden', role: 'toolbar', 'aria-label': 'Quick actions' }),
        el('div', { id: 'quick-action-mode', class: 'qa-mode hidden' }),
        el('div', { id: 'quick-action-slash', class: 'qa-slash-menu hidden', role: 'listbox', 'aria-label': 'Quick actions' }),
        el('textarea', { id: 'message-input', placeholder: 'Type your message...', rows: '1' }),
        composerToolbar(),
      ]),
    ]),
  ]);
}

/** The main chat area: headers, the message list and the composer. */
function main(): HTMLElement {
  return el('main', { class: 'main' }, [
    el('header', { class: 'mobile-header' }, [
      createIconButton({ id: 'menu-btn', class: 'btn-icon' }, MENU_ICON),
      el('span', { id: 'current-chat-title' }, [APP_NAME]),
      el('button', { id: 'conversation-compaction-mobile', type: 'button', class: 'chat-header-compaction hidden' }),
      el('span', { id: 'conversation-cost-mobile', class: 'chat-header-cost' }),
    ]),
    el('header', { id: 'chat-header', class: 'chat-header hidden' }),
    el('div', { id: 'messages', class: 'messages' }, [createWelcomeMessage()]),
    composer(),
  ]);
}

/** The image lightbox (opened by Lightbox.ts). */
function lightbox(): HTMLElement {
  return el('div', { id: 'lightbox', class: 'lightbox hidden', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Image viewer' }, [
    el('div', { class: 'lightbox-loader' }, [
      el('div', { class: 'loading-dots' }, [el('span'), el('span'), el('span')]),
      el('p', {}, ['Loading image...']),
    ]),
    el('div', { class: 'lightbox-toolbar' }, [
      el('div', { class: 'lightbox-meta' }, [
        el('span', { id: 'lightbox-counter', class: 'lightbox-counter' }),
        el('span', { id: 'lightbox-filename', class: 'lightbox-filename' }),
      ]),
      el('div', { class: 'lightbox-toolbar-actions' }, [
        createIconButton({ class: 'lightbox-btn lightbox-download', 'aria-label': 'Download image' }, DOWNLOAD_ICON),
        createIconButton({ class: 'lightbox-btn lightbox-fullscreen', 'aria-label': 'Toggle fullscreen' }, MAXIMIZE_ICON),
        createIconButton({ class: 'lightbox-btn lightbox-close', 'aria-label': 'Close' }, CLOSE_ICON),
      ]),
    ]),
    createIconButton({ class: 'lightbox-nav lightbox-prev', 'aria-label': 'Previous image' }, CHEVRON_LEFT_ICON),
    createIconButton({ class: 'lightbox-nav lightbox-next', 'aria-label': 'Next image' }, CHEVRON_RIGHT_ICON),
    el('div', { class: 'lightbox-container' }, [
      el('img', { id: 'lightbox-img', src: '', alt: 'Full size image', draggable: 'false' }),
    ]),
  ]);
}

/**
 * Shells for the info popups; their contents are built on open. The
 * settings shell's contents and handlers lazy-load from SettingsPopup.ts on
 * first open - keep the id in sync.
 */
function popupShells(): HTMLElement[] {
  return [
    createPopupShell('sources-popup'),
    createPopupShell('imagegen-popup'),
    createPopupShell('message-cost-popup'),
    createCostHistoryPopupShell(),
    createCompactionPopupShell(),
    createPopupShell('settings-popup'),
  ];
}

/** The sign-in overlay (shown and hidden by startup/auth.ts). */
function loginOverlay(): HTMLElement {
  return el('div', { id: 'login-overlay', class: 'login-overlay hidden' }, [
    el('div', { class: 'login-box' }, [
      el('img', { class: 'login-logo', src: '/static/icon-192.png', alt: '', width: '64', height: '64' }),
      el('h2', {}, [APP_NAME]),
      el('p', {}, ['Sign in to continue']),
      el('div', { id: 'google-login-btn', class: 'google-btn-container' }),
      el('a', { href: '/privacy', class: 'login-privacy-link', target: '_blank' }, ['Privacy Policy']),
    ]),
  ]);
}

/**
 * Render the app shell into the #app element.
 */
export function mountAppShell(app: HTMLDivElement): void {
  app.replaceChildren(sidebar(), main(), lightbox(), ...popupShells(), loginOverlay());

  // Booting straight into a route (deep link / PWA relaunch) must show a
  // loading state, not the new-chat welcome screen - the welcome flashing
  // before messages arrive reads as landing in the wrong place
  const bootRoute = parseHash(window.location.hash);
  if (bootRoute.type !== 'home' && bootRoute.type !== 'unknown') {
    const messagesEl = getElementById<HTMLDivElement>('messages');
    if (messagesEl) {
      clearElement(messagesEl);
      showConversationLoader();
    }
  }
}
