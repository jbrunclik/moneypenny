import { getElementById } from '../utils/dom';
import { SETTINGS_ICON, CLOSE_ICON, SUN_ICON, MOON_ICON, MONITOR_ICON } from '../utils/icons';
import { settings } from '../api/client';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import {
  type ColorScheme,
  getStoredColorScheme,
  saveColorScheme,
  applyColorScheme,
  setupSystemPreferenceListener,
} from '../utils/theme';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';

const log = createLogger('settings-popup');

const POPUP_ID = 'settings-popup';
const CHAR_LIMIT = 2000;

/** Current custom instructions value */
let currentInstructions = '';

/** Current color scheme value */
let currentColorScheme: ColorScheme = 'system';

/**
 * Render color scheme option
 */
function renderColorSchemeOption(
  value: ColorScheme,
  icon: string,
  label: string,
  selected: boolean
): string {
  return `
    <button
      type="button"
      class="settings-color-scheme-option${selected ? ' selected' : ''}"
      data-color-scheme="${value}"
    >
      <span class="settings-color-scheme-icon">${icon}</span>
      <span class="settings-color-scheme-label">${label}</span>
    </button>
  `;
}

/**
 * Render the popup content
 */
function renderContent(instructions: string, colorScheme: ColorScheme): string {
  const charCount = instructions.length;
  const charCountClass = charCount > CHAR_LIMIT ? 'error' : charCount > CHAR_LIMIT * 0.9 ? 'warning' : '';

  return `
    <div class="settings-body">
      <div class="settings-field">
        <label class="settings-label">Appearance</label>
        <div class="settings-color-scheme">
          ${renderColorSchemeOption('light', SUN_ICON, 'Light', colorScheme === 'light')}
          ${renderColorSchemeOption('dark', MOON_ICON, 'Dark', colorScheme === 'dark')}
          ${renderColorSchemeOption('system', MONITOR_ICON, 'System', colorScheme === 'system')}
        </div>
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field">
        <label class="settings-label" for="custom-instructions">Custom Instructions</label>
        <p class="settings-helper">Tell the AI how to respond (e.g., "respond in Czech", "be concise", "use bullet points")</p>
        <textarea
          id="custom-instructions"
          class="settings-textarea"
          placeholder="Enter your custom instructions here..."
          maxlength="${CHAR_LIMIT}"
        >${instructions}</textarea>
        <span class="settings-char-count ${charCountClass}">${charCount}/${CHAR_LIMIT}</span>
      </div>
    </div>
  `;
}

/**
 * Update character count display
 */
function updateCharCount(textarea: HTMLTextAreaElement): void {
  const charCount = textarea.value.length;
  const charCountEl = document.querySelector('.settings-char-count');
  if (charCountEl) {
    charCountEl.textContent = `${charCount}/${CHAR_LIMIT}`;
    charCountEl.className = 'settings-char-count';
    if (charCount > CHAR_LIMIT) {
      charCountEl.classList.add('error');
    } else if (charCount > CHAR_LIMIT * 0.9) {
      charCountEl.classList.add('warning');
    }
  }
}

/**
 * Save settings
 */
async function saveSettings(): Promise<void> {
  const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement;
  if (!textarea) return;

  const instructions = textarea.value.trim();

  // Check if value changed
  if (instructions === currentInstructions) {
    closeSettingsPopup();
    return;
  }

  log.debug('Saving settings', { instructionsLength: instructions.length });

  try {
    await settings.update({ custom_instructions: instructions });
    currentInstructions = instructions;
    closeSettingsPopup();
    toast.success('Settings saved');
    log.info('Settings saved', { instructionsLength: instructions.length });
  } catch (error) {
    log.error('Failed to save settings', { error });
    toast.error('Failed to save settings');
  }
}

/**
 * Handle color scheme option click
 */
function handleColorSchemeClick(scheme: ColorScheme): void {
  if (scheme === currentColorScheme) return;

  // Update selection UI
  const options = document.querySelectorAll('.settings-color-scheme-option');
  options.forEach((option) => {
    const optionScheme = (option as HTMLElement).dataset.colorScheme as ColorScheme;
    option.classList.toggle('selected', optionScheme === scheme);
  });

  // Apply and save the theme
  currentColorScheme = scheme;
  saveColorScheme(scheme);
  applyColorScheme(scheme);

  log.info('Color scheme changed', { scheme });
}

/**
 * Open the settings popup
 */
export async function openSettingsPopup(): Promise<void> {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Load current color scheme
  currentColorScheme = getStoredColorScheme();

  // Show popup with loading state
  const content = popup.querySelector('.info-popup-content');
  if (content) {
    content.innerHTML = `
      <div class="info-popup-header">
        <span class="info-popup-icon">${SETTINGS_ICON}</span>
        <h3>Settings</h3>
        <button class="info-popup-close" aria-label="Close">${CLOSE_ICON}</button>
      </div>
      <div class="info-popup-body settings-body">
        <div class="settings-loading">Loading settings...</div>
      </div>
      <div class="info-popup-footer settings-footer">
        <button class="btn btn-primary settings-save-btn" disabled>Save</button>
      </div>
    `;

    // Attach close handler
    content.querySelector('.info-popup-close')?.addEventListener('click', closeSettingsPopup);
  }

  popup.classList.remove('hidden');

  // Fetch settings
  try {
    log.debug('Fetching settings');
    const data = await settings.get();
    currentInstructions = data.custom_instructions || '';
    log.info('Settings loaded', { instructionsLength: currentInstructions.length });

    // Update popup body
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.outerHTML = `<div class="info-popup-body">${renderContent(currentInstructions, currentColorScheme)}</div>`;
    }

    // Enable save button and attach handlers
    const saveBtn = popup.querySelector('.settings-save-btn') as HTMLButtonElement;
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.addEventListener('click', saveSettings);
    }

    // Attach textarea input handler for character count
    const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement;
    if (textarea) {
      textarea.addEventListener('input', () => updateCharCount(textarea));
      // Focus the textarea
      textarea.focus();
    }

    // Attach color scheme click handlers
    const colorSchemeOptions = popup.querySelectorAll('.settings-color-scheme-option');
    colorSchemeOptions.forEach((option) => {
      option.addEventListener('click', () => {
        const scheme = (option as HTMLElement).dataset.colorScheme as ColorScheme;
        handleColorSchemeClick(scheme);
      });
    });
  } catch (error) {
    log.error('Failed to load settings', { error });
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.innerHTML = `
        <div class="settings-error">
          <p>Failed to load settings.</p>
          <button class="btn btn-secondary settings-retry-btn">Retry</button>
        </div>
      `;
    }
  }
}

/**
 * Close the settings popup
 */
export function closeSettingsPopup(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (popup) {
    popup.classList.add('hidden');
  }
}

/**
 * Initialize settings popup and theme system
 */
export function initSettingsPopup(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Close on backdrop click
  popup.addEventListener('click', (e) => {
    if (e.target === popup) {
      closeSettingsPopup();
    }
  });

  // Register with centralized Escape key handler
  registerPopupEscapeHandler(POPUP_ID, closeSettingsPopup);

  // Event delegation for retry button
  popup.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;

    // Retry button
    if (target.classList.contains('settings-retry-btn')) {
      openSettingsPopup();
    }
  });

  // Set up system preference listener for when 'system' is selected
  // Note: This listener is never cleaned up since the popup/app lives forever
  setupSystemPreferenceListener(() => {
    const currentScheme = getStoredColorScheme();
    if (currentScheme === 'system') {
      // Re-apply when system preference changes and 'system' is selected
      applyColorScheme('system');
    }
  });

  log.debug('Settings popup initialized');
}

/**
 * Get HTML for settings popup shell
 */
export function getSettingsPopupHtml(): string {
  return `
    <div id="${POPUP_ID}" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>
  `;
}
