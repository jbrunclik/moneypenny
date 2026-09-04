/**
 * Field form shown when a quick action has fields. Popover anchored to the
 * chip on desktop, bottom sheet on mobile (both share the same DOM; CSS
 * switches layout at the 768px breakpoint). Presentation only.
 */
import type { QuickAction } from '../types/api';
import { escapeHtml, autoResizeTextarea } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import { isMobileViewport } from './MessageInput';

let overlay: HTMLElement | null = null;
let keydownHandler: ((e: KeyboardEvent) => void) | null = null;

export function closeQuickActionForm(): void {
  if (keydownHandler) document.removeEventListener('keydown', keydownHandler);
  keydownHandler = null;
  overlay?.remove();
  overlay = null;
}

export function showQuickActionForm(
  action: QuickAction,
  anchor: HTMLElement,
  onSend: (values: Record<string, string>) => void
): void {
  closeQuickActionForm();

  overlay = document.createElement('div');
  overlay.className = 'quick-action-form-overlay';

  const form = document.createElement('div');
  form.className = 'quick-action-form';
  form.setAttribute('role', 'dialog');
  form.setAttribute('aria-modal', 'true');
  form.setAttribute('aria-label', action.label);
  form.innerHTML = `
    <div class="quick-action-form-title">${escapeHtml(action.emoji)} ${escapeHtml(action.label)}</div>
    <div class="quick-action-form-fields">
      ${action.fields
        .map(
          (f, i) => `
        <div class="quick-action-form-field">
          <label for="qa-field-${i}">${escapeHtml(f)}</label>
          <textarea id="qa-field-${i}" data-field="${escapeHtml(f)}" rows="1" placeholder="Optional"></textarea>
        </div>`
        )
        .join('')}
    </div>
    <div class="quick-action-form-actions">
      <button type="button" class="quick-action-form-cancel">Cancel</button>
      <button type="button" class="quick-action-form-send">Send</button>
    </div>`;
  overlay.appendChild(form);
  document.body.appendChild(overlay);

  // Desktop: anchor the popover above the chip. Mobile: CSS pins it bottom.
  if (!isMobileViewport()) {
    const rect = anchor.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - form.offsetWidth - 8));
    form.style.left = `${left}px`;
    form.style.bottom = `${window.innerHeight - rect.top + 8}px`;
  }

  const collect = (): Record<string, string> => {
    const values: Record<string, string> = {};
    for (const area of form.querySelectorAll<HTMLTextAreaElement>('textarea')) {
      values[area.dataset.field ?? ''] = area.value;
    }
    return values;
  };
  const submit = (): void => {
    const values = collect();
    closeQuickActionForm();
    onSend(values);
  };

  form.querySelector('.quick-action-form-send')!.addEventListener('click', submit);
  form.querySelector('.quick-action-form-cancel')!.addEventListener('click', closeQuickActionForm);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeQuickActionForm();
  });
  form.addEventListener('input', (e) => {
    const t = e.target;
    if (t instanceof HTMLTextAreaElement) autoResizeTextarea(t);
  });
  form.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  });
  keydownHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeQuickActionForm();
      return;
    }
    trapTabKey(form, e);
  };
  document.addEventListener('keydown', keydownHandler);

  form.querySelector<HTMLTextAreaElement>('textarea')?.focus();
}
