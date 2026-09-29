import { getElementById } from '../../utils/dom';
import { createLogger } from '../../utils/logger';

export const log = createLogger('settings-popup');

export const POPUP_ID = 'settings-popup';

/**
 * Label row shared by every integration field (icon + title).
 */
export function renderFieldLabel(icon: string, label: string): string {
  return `
    <label class="settings-label settings-label-with-icon">
      <span class="settings-label-icon">${icon}</span>
      ${label}
    </label>
  `;
}

/**
 * Re-render one `.settings-field[data-section=...]` in the open popup
 * (label + body). No-op when the popup or field is not in the DOM.
 * Button handlers survive because they are delegated on the popup root.
 */
export function rerenderField(section: string, icon: string, label: string, bodyHtml: string): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  const field = popup.querySelector(`.settings-field[data-section="${section}"]`);
  if (!field) return;

  field.innerHTML = `
    ${renderFieldLabel(icon, label)}
    ${bodyHtml}
  `;
}

/**
 * Show the transient "Saved" indicator next to a field.
 */
export function showSavedIndicator(fieldId: string): void {
  const indicator = document.querySelector<HTMLElement>(
    `.settings-saved-indicator[data-saved-for="${fieldId}"]`,
  );
  if (!indicator) return;
  indicator.classList.add('visible');
  window.setTimeout(() => indicator.classList.remove('visible'), 1500);
}
