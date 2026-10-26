import { createElement } from '../../utils/dom';
import { SUN_ICON, MOON_ICON, MONITOR_ICON, LANGUAGE_ICON, createIconElement, type IconHtml } from '../../utils/icons';
import { settings } from '../../api/settings';
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
import { fieldLabel, helper, log, toggle } from './shared';

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
 * A color scheme option button
 */
function colorSchemeOption(value: ColorScheme, icon: IconHtml, label: string, selected: boolean): HTMLButtonElement {
  return createElement(
    'button',
    { type: 'button', class: `settings-color-scheme-option${selected ? ' selected' : ''}`, 'data-color-scheme': value },
    [
      createIconElement('settings-color-scheme-icon', icon),
      createElement('span', { class: 'settings-color-scheme-label' }, [label]),
    ]
  );
}

/**
 * The "Appearance & Language" tab section.
 */
export function renderAppearanceSection(): HTMLElement {
  const colorScheme = currentColorScheme;
  return createElement('div', { class: 'settings-section active', 'data-settings-section': 'appearance' }, [
    createElement('div', { class: 'settings-section-title' }, ['Appearance & Language']),
    createElement('div', { class: 'settings-field' }, [
      fieldLabel(MONITOR_ICON, 'Appearance'),
      createElement('div', { class: 'settings-color-scheme' }, [
        colorSchemeOption('light', SUN_ICON, 'Light', colorScheme === 'light'),
        colorSchemeOption('dark', MOON_ICON, 'Dark', colorScheme === 'dark'),
        colorSchemeOption('system', MONITOR_ICON, 'System', colorScheme === 'system'),
      ]),
      toggle('sidebar-previews-enabled', isSidebarPreviewsEnabled(), 'Show message previews in the sidebar', ' settings-toggle-spaced'),
      toggle('swipe-quick-delete', getSwipeQuickAction() === 'delete', 'Swipe to delete instead of archive', ' settings-toggle-spaced'),
    ]),
    createElement('div', { class: 'settings-divider' }),
    createElement('div', { class: 'settings-field', 'data-section': 'language-pref' }, [
      fieldLabel(LANGUAGE_ICON, 'Primary Language', 'preferred-language'),
      helper('The assistant replies in this language, even to app-generated messages like session starts and agent runs.'),
      createElement(
        'select',
        { id: 'preferred-language', class: 'settings-input settings-language-select' },
        LANGUAGE_OPTIONS.map((opt) =>
          createElement('option', { value: opt.value, ...(opt.value === currentPreferredLanguage ? { selected: '' } : {}) }, [opt.label])
        )
      ),
    ]),
  ]);
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
