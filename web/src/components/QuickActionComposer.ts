/**
 * Composer mode for a quick action with questions: a header (emoji, label,
 * cancel) and one compact input per question, rendered INSIDE the composer
 * pill above the note textarea. Presentation only; core/quick-actions.ts
 * owns the state and the send.
 */
import type { QuickAction } from '../types/api';
import { createElement } from '../utils/dom';
import { CLOSE_ICON, setIcon } from '../utils/icons';

export interface QuickActionComposerOptions {
  action: QuickAction;
  onCancel: () => void;
  /** Enter pressed inside field `index`. */
  onFieldEnter: (index: number, isLast: boolean) => void;
  onEscape: () => void;
}

export function renderQuickActionComposer(
  container: HTMLElement,
  opts: QuickActionComposerOptions
): void {
  const { action } = opts;
  const cancel = createElement('button', {
    type: 'button',
    class: 'qa-mode-cancel',
    'aria-label': `Cancel ${action.label}`,
    title: 'Cancel',
  });
  setIcon(cancel, CLOSE_ICON);
  const header = createElement('div', { class: 'qa-mode-header' }, [
    createElement('span', { class: 'qa-mode-emoji', 'aria-hidden': 'true' }, [action.emoji]),
    createElement('span', { class: 'qa-mode-label' }, [action.label]),
    cancel,
  ]);
  const fields =
    action.fields.length > 0 &&
    createElement(
      'div',
      { class: 'qa-mode-fields' },
      action.fields.map((f, i) =>
        createElement('label', { class: 'qa-mode-field' }, [
          createElement('span', { class: 'qa-mode-field-label' }, [f]),
          createElement('input', {
            type: 'text',
            class: 'qa-mode-field-input',
            'data-field': f,
            'data-index': String(i),
            autocomplete: 'off',
            enterkeyhint: i === action.fields.length - 1 ? 'send' : 'next',
          }),
        ])
      )
    );
  container.replaceChildren(header, ...(fields ? [fields] : []));

  container.querySelector('.qa-mode-cancel')?.addEventListener('click', opts.onCancel);
  container.addEventListener('keydown', (e) => {
    const target = e.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      opts.onEscape();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const index = Number(target.dataset.index);
      opts.onFieldEnter(index, index === action.fields.length - 1);
    }
  });
}

export function readQuickActionComposerValues(container: HTMLElement): Record<string, string> {
  const values: Record<string, string> = {};
  for (const input of container.querySelectorAll<HTMLInputElement>('.qa-mode-field-input')) {
    values[input.dataset.field ?? ''] = input.value;
  }
  return values;
}

export function focusQuickActionField(container: HTMLElement, index: number): boolean {
  const input = container.querySelector<HTMLInputElement>(
    `.qa-mode-field-input[data-index="${index}"]`
  );
  if (!input) return false;
  input.focus();
  return true;
}
