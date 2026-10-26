import { createElement, getElementById } from '../../utils/dom';
import { createIconElement, type IconHtml } from '../../utils/icons';
import { createLogger } from '../../utils/logger';

export const log = createLogger('settings-popup');

export const POPUP_ID = 'settings-popup';

/**
 * Label row shared by every settings field (icon + title).
 */
export function fieldLabel(icon: IconHtml, label: string, forId?: string): HTMLLabelElement {
  return createElement('label', { class: 'settings-label settings-label-with-icon', ...(forId ? { for: forId } : {}) }, [
    createIconElement('settings-label-icon', icon),
    ` ${label}`,
  ]);
}

/** A `.settings-field` of an integration: its label, then its body. */
export function settingsField(section: string, icon: IconHtml, label: string, body: Node[]): HTMLElement {
  return createElement('div', { class: 'settings-field', 'data-section': section }, [fieldLabel(icon, label), ...body]);
}

/** A `.settings-helper` paragraph (muted with `muted`). */
export function helper(text: string, muted = false): HTMLParagraphElement {
  return createElement('p', { class: muted ? 'settings-helper settings-helper-muted' : 'settings-helper' }, [text]);
}

/** A type="button" button with a text label. */
export function textButton(className: string, label: string): HTMLButtonElement {
  return createElement('button', { type: 'button', class: className }, [label]);
}

/**
 * An integration's status line: `<span class="settings-X-status"><span
 * class="settings-X-icon kind">ICON</span> text</span>`.
 */
export function statusLine(prefix: string, kind: 'connected' | 'warning', icon: IconHtml, text: string): HTMLElement {
  return createElement('span', { class: `settings-${prefix}-status` }, [
    createIconElement(`settings-${prefix}-icon ${kind}`, icon),
    ` ${text}`,
  ]);
}

/** A checkbox, checked when `checked`. */
export function checkbox(attributes: Record<string, string>, checked: boolean): HTMLInputElement {
  return createElement('input', { type: 'checkbox', ...attributes, ...(checked ? { checked: '' } : {}) });
}

/** A toggle switch row: checkbox, the switch, its text. */
export function toggle(id: string, checked: boolean, text: string, extraClass = ''): HTMLLabelElement {
  return createElement('label', { class: `toggle-label${extraClass}` }, [
    checkbox({ id }, checked),
    createElement('span', { class: 'toggle-switch' }),
    createElement('span', { class: 'toggle-text' }, [text]),
  ]);
}

/**
 * Re-render one `.settings-field[data-section=...]` in the open popup
 * (label + body). No-op when the popup or field is not in the DOM.
 * Button handlers survive because they are delegated on the popup root.
 */
export function rerenderField(section: string, icon: IconHtml, label: string, body: Node[]): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  const field = popup.querySelector(`.settings-field[data-section="${section}"]`);
  if (!field) return;

  field.replaceChildren(fieldLabel(icon, label), ...body);
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
