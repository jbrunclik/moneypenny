/**
 * The app shell: the static markup every view renders into, and mounting it.
 */
import { renderWelcomeMessageHtml } from '../../components/WelcomeMessage';
import { showConversationLoader } from '../../components/messages';
import { getCostHistoryPopupHtml } from '../../components/CostHistoryPopup';
import { getCompactionPopupHtml } from '../../components/CompactionIndicator';
import { APP_NAME } from '../../config';
import { getElementById, clearElement } from '../../utils/dom';
import { parseHash } from '../../router/deeplink';
import { ATTACH_ICON, CHEVRON_DOWN_ICON, CHEVRON_LEFT_ICON, CHEVRON_RIGHT_ICON, SLIDERS_ICON, CLOSE_ICON, DOWNLOAD_ICON, MAXIMIZE_ICON, SEND_ICON, MICROPHONE_ICON, STREAM_ICON, SEARCH_ICON, SPARKLES_ICON, PLUS_ICON, INCOGNITO_ICON, MENU_ICON, DELETE_ICON } from '../../utils/icons';

/** The sidebar: brand, New Chat, selection bar, search, list, user info. */
function sidebarHtml(): string {
  return `    <!-- Sidebar -->
    <aside id="sidebar" class="sidebar">
      <div class="sidebar-header">
        <div class="sidebar-brand">
          <img class="sidebar-logo" src="/static/icon-192.png" alt="" width="28" height="28">
          <h1>${APP_NAME}</h1>
        </div>
        <button id="new-chat-btn" class="btn btn-primary btn-new-chat">${PLUS_ICON} New Chat</button>
      </div>
      <div id="selection-bar" class="selection-bar hidden" role="toolbar" aria-label="Select chats">
        <button id="selection-cancel" type="button" class="selection-bar-btn">Cancel</button>
        <span class="selection-count" aria-live="polite">0 selected</span>
        <button id="selection-all" type="button" class="selection-bar-btn">Select all</button>
      </div>
      <div id="search-container" class="search-container"></div>
      <div id="conversations-list" class="conversations-list"></div>
      <div class="sidebar-footer">
        <div id="user-info" class="user-info"></div>
      </div>
      <div id="selection-footer" class="selection-footer hidden">
        <button id="selection-trash" type="button" class="btn btn-primary" disabled>${DELETE_ICON} Move 0 to trash</button>
      </div>
    </aside>
`;
}

/** The composer's toolbar: model, toggles, voice, attach, send. */
function composerToolbarHtml(): string {
  return `            <div class="input-toolbar">
            <div class="toolbar-left">
              <div class="model-selector">
                <button id="model-selector-btn" class="model-selector-btn">
                  <span id="current-model-name">Loading...</span>
                  <span class="dropdown-arrow">${CHEVRON_DOWN_ICON}</span>
                </button>
                <div id="model-dropdown" class="model-dropdown hidden"></div>
              </div>
              <button id="toolbar-options-btn" class="btn-toolbar" aria-label="Message options" aria-expanded="false">
                ${SLIDERS_ICON}
              </button>
              <div class="toolbar-toggles">
                <button id="stream-btn" class="btn-toolbar active" title="Toggle streaming" aria-label="Toggle streaming" aria-pressed="true">
                  ${STREAM_ICON}<span class="toolbar-toggle-label">Streaming</span>
                </button>
                <button id="search-btn" class="btn-toolbar" aria-pressed="false" title="Force web search for next message" aria-label="Force web search for next message">
                  ${SEARCH_ICON}<span class="toolbar-toggle-label">Web search</span>
                </button>
                <button id="imagegen-btn" class="btn-toolbar" aria-pressed="false" title="Force image generation for next message" aria-label="Force image generation for next message">
                  ${SPARKLES_ICON}<span class="toolbar-toggle-label">Generate image</span>
                </button>
                <button id="anonymous-btn" class="btn-toolbar" aria-pressed="false" title="Anonymous mode - disable memory and integrations" aria-label="Anonymous mode">
                  ${INCOGNITO_ICON}<span class="toolbar-toggle-label">Incognito</span>
                </button>
              </div>
            </div>
            <div class="toolbar-right">
              <button id="voice-btn" class="btn-toolbar btn-voice" title="Voice input" aria-label="Voice input" aria-pressed="false">
                ${MICROPHONE_ICON}
              </button>
              <button id="attach-btn" class="btn-toolbar" title="Attach files" aria-label="Attach files">
                ${ATTACH_ICON}
              </button>
              <button id="send-btn" class="btn btn-send" aria-label="Send message" disabled>
                ${SEND_ICON}
              </button>
            </div>
            </div>
`;
}

/** The input area at the bottom of the chat. */
function composerHtml(): string {
  return `      <div class="input-area">
        <div class="input-wrapper">
          <div id="file-preview" class="file-preview hidden"></div>
          <input type="file" id="file-input" multiple accept="image/*,video/mp4,video/quicktime,video/webm,application/pdf,text/plain,text/markdown,text/csv,application/json">
          <div id="input-container" class="input-container">
            <div id="quick-actions-bar" class="quick-actions-bar hidden" role="toolbar" aria-label="Quick actions"></div>
            <div id="quick-action-mode" class="qa-mode hidden"></div>
            <div id="quick-action-slash" class="qa-slash-menu hidden" role="listbox" aria-label="Quick actions"></div>
            <textarea id="message-input" placeholder="Type your message..." rows="1"></textarea>
${composerToolbarHtml()}          </div>
        </div>
      </div>
`;
}

/** The main chat area: headers, the message list and the composer. */
function mainHtml(): string {
  return `    <!-- Main chat area -->
    <main class="main">
      <header class="mobile-header">
        <button id="menu-btn" class="btn-icon">${MENU_ICON}</button>
        <span id="current-chat-title">${APP_NAME}</span>
        <button id="conversation-compaction-mobile" type="button" class="chat-header-compaction hidden"></button>
        <span id="conversation-cost-mobile" class="chat-header-cost"></span>
      </header>

      <header id="chat-header" class="chat-header hidden"></header>

      <div id="messages" class="messages">
        ${renderWelcomeMessageHtml()}
      </div>

${composerHtml()}    </main>
`;
}

/** The image lightbox (opened by Lightbox.ts). */
function lightboxHtml(): string {
  return `    <!-- Lightbox -->
    <div id="lightbox" class="lightbox hidden" role="dialog" aria-modal="true" aria-label="Image viewer">
      <div class="lightbox-loader">
        <div class="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <p>Loading image...</p>
      </div>
      <div class="lightbox-toolbar">
        <div class="lightbox-meta">
          <span id="lightbox-counter" class="lightbox-counter"></span>
          <span id="lightbox-filename" class="lightbox-filename"></span>
        </div>
        <div class="lightbox-toolbar-actions">
          <button class="lightbox-btn lightbox-download" aria-label="Download image">
            ${DOWNLOAD_ICON}
          </button>
          <button class="lightbox-btn lightbox-fullscreen" aria-label="Toggle fullscreen">
            ${MAXIMIZE_ICON}
          </button>
          <button class="lightbox-btn lightbox-close" aria-label="Close">
            ${CLOSE_ICON}
          </button>
        </div>
      </div>
      <button class="lightbox-nav lightbox-prev" aria-label="Previous image">
        ${CHEVRON_LEFT_ICON}
      </button>
      <button class="lightbox-nav lightbox-next" aria-label="Next image">
        ${CHEVRON_RIGHT_ICON}
      </button>
      <div class="lightbox-container">
        <img id="lightbox-img" src="" alt="Full size image" draggable="false">
      </div>
    </div>
`;
}

/** Shells for the info popups; their contents are rendered on open. */
function popupShellsHtml(): string {
  return `    <!-- Sources Popup -->
    <div id="sources-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Image Generation Popup -->
    <div id="imagegen-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Message Cost Popup -->
    <div id="message-cost-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Cost History Popup -->
    ${getCostHistoryPopupHtml()}

    <!-- Conversation Compaction Popup -->
    ${getCompactionPopupHtml()}

    <!-- Settings Popup shell (contents + handlers lazy-load from
         SettingsPopup.ts on first open - keep the id in sync) -->
    <div id="settings-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>
`;
}

/** The sign-in overlay (shown and hidden by startup/auth.ts). */
function loginOverlayHtml(): string {
  return `    <!-- Login overlay -->
    <div id="login-overlay" class="login-overlay hidden">
      <div class="login-box">
        <img class="login-logo" src="/static/icon-192.png" alt="" width="64" height="64">
        <h2>${APP_NAME}</h2>
        <p>Sign in to continue</p>
        <div id="google-login-btn" class="google-btn-container"></div>
        <a href="/privacy" class="login-privacy-link" target="_blank">Privacy Policy</a>
      </div>
    </div>
`;
}

/**
 * Render the app shell HTML template.
 */
function renderAppShell(): string {
  return `
${sidebarHtml()}
${mainHtml()}
${lightboxHtml()}
${popupShellsHtml()}
${loginOverlayHtml()}  `;
}

/**
 * Render the app shell into the #app element.
 */
export function mountAppShell(app: HTMLDivElement): void {
  app.innerHTML = renderAppShell();

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
