import { getElementById } from '../utils/dom';
import { CLOSE_ICON } from '../utils/icons';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';

/**
 * Configuration for creating an info popup
 */
export interface PopupConfig {
  /** Unique ID for the popup element */
  id: string;
  /** Custom event name that triggers this popup (e.g., 'sources:open') */
  eventName: string;
  /** SVG icon to display in the header */
  icon: string;
  /** Title displayed in the popup header */
  title: string;
  /** CSS class for popup-specific styling (e.g., 'sources' or 'imagegen') */
  styleClass: string;
}

/**
 * Interface for a popup instance
 */
export interface PopupInstance<T> {
  /** Initialize popup event handlers */
  init: () => void;
  /** Open popup with data */
  open: (data: T) => void;
  /** Close popup */
  close: () => void;
}

/**
 * Create a reusable info popup component
 *
 * @param config - Popup configuration
 * @param renderContent - Function that renders the popup body content
 * @returns Popup instance with init, open, and close methods
 */
export function createPopup<T>(
  config: PopupConfig,
  renderContent: (data: T) => string
): PopupInstance<T> {
  const { id, eventName, icon, title, styleClass } = config;

  /**
   * Close the popup
   */
  function close(): void {
    const popup = getElementById<HTMLDivElement>(id);
    if (popup) {
      popup.classList.add('hidden');
    }
  }

  /**
   * Open the popup with data
   */
  function open(data: T): void {
    const popup = getElementById<HTMLDivElement>(id);
    const content = popup?.querySelector('.info-popup-content');

    if (!popup || !content) return;

    // Render popup content
    content.innerHTML = `
      <div class="info-popup-header">
        <span class="info-popup-icon">${icon}</span>
        <h3>${title}</h3>
        <button class="info-popup-close" aria-label="Close">${CLOSE_ICON}</button>
      </div>
      <div class="info-popup-body ${styleClass}-body">
        ${renderContent(data)}
      </div>
    `;

    // Attach close handler to new button
    content.querySelector('.info-popup-close')?.addEventListener('click', close);

    // Show popup
    popup.classList.remove('hidden');
  }

  /**
   * Initialize popup event handlers
   */
  function init(): void {
    const popup = getElementById<HTMLDivElement>(id);

    // Close on backdrop click
    popup?.addEventListener('click', (e) => {
      if (e.target === popup) {
        close();
      }
    });

    // Register with centralized Escape key handler
    registerPopupEscapeHandler(id, close);

    // Listen for custom open events
    window.addEventListener(eventName, ((e: CustomEvent) => {
      const data = e.detail as T;
      if (data) {
        open(data);
      }
    }) as EventListener);
  }

  return { init, open, close };
}

/**
 * Create popup HTML shell for embedding in the app
 *
 * @param id - Unique ID for the popup element
 * @returns HTML string for the popup container
 */
export function createPopupHtml(id: string): string {
  return `
    <div id="${id}" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>
  `;
}