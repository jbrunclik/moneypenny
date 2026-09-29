import { escapeHtml } from '../../utils/dom';
import { SUN_ICON, MOON_ICON, MONITOR_ICON, LANGUAGE_ICON } from '../../utils/icons';
import { settings } from '../../api/client';
import { toast } from '../Toast';
import {
  type ColorScheme,
  getStoredColorScheme,
  saveColorScheme,
  applyColorScheme,
} from '../../utils/theme';
import type { UserSettings } from '../../types/api';
import { renderConversationsList } from '../Sidebar';
import {
  isSidebarPreviewsEnabled,
  setSidebarPreviewsEnabled,
  getSwipeQuickAction,
  setSwipeQuickAction,
} from '../../utils/preferences';
import { log } from './shared';

/** Current color scheme value */
let currentColorScheme: ColorScheme = 'system';

/** Current primary language ('' = auto: match the user's messages) */
let currentPreferredLanguage = '';

/** Primary-language options: stored value (English name) + display label */
const LANGUAGE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Auto (match my messages)' },
  { value: 'Czech', label: 'Čeština' },
  { value: 'English', label: 'English' },
  { value: 'German', label: 'Deutsch' },
  { value: 'Slovak', label: 'Slovenčina' },
  { value: 'Polish', label: 'Polski' },
  { value: 'Spanish', label: 'Español' },
  { value: 'French', label: 'Français' },
  { value: 'Italian', label: 'Italiano' },
];

/** Load the stored color scheme (called when the popup opens). */
export function loadColorScheme(): void {
  currentColorScheme = getStoredColorScheme();
}

/** Adopt the server-side appearance settings after a settings fetch. */
export function loadAppearanceSettings(data: UserSettings): void {
  currentPreferredLanguage = data.preferred_language || '';
}

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
 * Render the "Appearance & Language" tab section.
 */
export function renderAppearanceSection(): string {
  const colorScheme = currentColorScheme;
  return `
      <div class="settings-section active" data-settings-section="appearance">
      <div class="settings-section-title">Appearance &amp; Language</div>
      <div class="settings-field">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${MONITOR_ICON}</span>
          Appearance
        </label>
        <div class="settings-color-scheme">
          ${renderColorSchemeOption('light', SUN_ICON, 'Light', colorScheme === 'light')}
          ${renderColorSchemeOption('dark', MOON_ICON, 'Dark', colorScheme === 'dark')}
          ${renderColorSchemeOption('system', MONITOR_ICON, 'System', colorScheme === 'system')}
        </div>
        <label class="toggle-label settings-toggle-spaced">
          <input type="checkbox" id="sidebar-previews-enabled" ${isSidebarPreviewsEnabled() ? 'checked' : ''}>
          <span class="toggle-switch"></span>
          <span class="toggle-text">Show message previews in the sidebar</span>
        </label>
        <label class="toggle-label settings-toggle-spaced">
          <input type="checkbox" id="swipe-quick-delete" ${getSwipeQuickAction() === 'delete' ? 'checked' : ''}>
          <span class="toggle-switch"></span>
          <span class="toggle-text">Swipe to delete instead of archive</span>
        </label>
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="language-pref">
        <label class="settings-label settings-label-with-icon" for="preferred-language">
          <span class="settings-label-icon">${LANGUAGE_ICON}</span>
          Primary Language
        </label>
        <p class="settings-helper">The assistant replies in this language, even to app-generated messages like session starts and agent runs.</p>
        <select id="preferred-language" class="settings-input settings-language-select">
          ${LANGUAGE_OPTIONS.map(
            (opt) =>
              `<option value="${escapeHtml(opt.value)}" ${opt.value === currentPreferredLanguage ? 'selected' : ''}>${escapeHtml(opt.label)}</option>`
          ).join('')}
        </select>
      </div>
      </div>
  `;
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

/** Attach the color scheme option click handlers after the body renders. */
export function bindColorSchemeOptions(popup: HTMLElement): void {
  const colorSchemeOptions = popup.querySelectorAll('.settings-color-scheme-option');
  colorSchemeOptions.forEach((option) => {
    option.addEventListener('click', () => {
      const scheme = (option as HTMLElement).dataset.colorScheme as ColorScheme;
      handleColorSchemeClick(scheme);
    });
  });
}

/**
 * Apply a primary-language change immediately ('' = auto).
 */
async function handlePreferredLanguageChange(select: HTMLSelectElement): Promise<void> {
  const value = select.value;
  try {
    await settings.update({ preferred_language: value });
    currentPreferredLanguage = value;
    const label = LANGUAGE_OPTIONS.find((o) => o.value === value)?.label ?? value;
    toast.success(value ? `Primary language set to ${label}` : 'Language set to auto');
  } catch (error) {
    log.error('Failed to update preferred language', { error });
    toast.error('Failed to update language.');
    select.value = currentPreferredLanguage;
  }
}

/** Delegated `change` handling for the appearance section's controls. */
export function handleAppearanceChange(target: HTMLElement): void {
  if (target.id === 'preferred-language') {
    void handlePreferredLanguageChange(target as HTMLSelectElement);
  }
  if (target.id === 'sidebar-previews-enabled') {
    setSidebarPreviewsEnabled((target as HTMLInputElement).checked);
    renderConversationsList();
  }
  if (target.id === 'swipe-quick-delete') {
    setSwipeQuickAction((target as HTMLInputElement).checked ? 'delete' : 'archive');
    renderConversationsList();
  }
}
