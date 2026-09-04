/**
 * Quick-actions chip bar: horizontally scrolling row of one-tap prompts
 * rendered above the composer in program conversations, plus a trailing
 * gear chip that opens the editor (the only entry point on mobile, where the
 * program header is hidden). Presentation only; core/quick-actions.ts decides
 * when it is mounted/visible and what a tap does.
 */
import type { QuickAction } from '../types/api';
import { clearElement, escapeHtml } from '../utils/dom';
import { SLIDERS_ICON } from '../utils/icons';

type TapHandler = (action: QuickAction, chip: HTMLElement) => void;

interface BarHandlers {
  actions: QuickAction[];
  onTap: TapHandler;
  onEdit: () => void;
}

// One delegated listener per container; re-renders swap the handlers.
const handlers = new WeakMap<HTMLElement, BarHandlers>();

export function renderQuickActionsBar(
  container: HTMLElement,
  actions: QuickAction[],
  onTap: TapHandler,
  onEdit: () => void = () => {}
): void {
  clearElement(container);
  const scroller = document.createElement('div');
  scroller.className = 'quick-actions-scroller';
  scroller.innerHTML =
    actions
      .map(
        (a) => `
      <button type="button" class="quick-action-chip" data-action-id="${escapeHtml(a.id)}" title="${escapeHtml(a.body)}">
        <span class="quick-action-chip-emoji" aria-hidden="true">${escapeHtml(a.emoji)}</span>
        <span class="quick-action-chip-label">${escapeHtml(a.label)}</span>
      </button>`
      )
      .join('') +
    `<button type="button" class="quick-action-edit-chip" title="Edit quick actions" aria-label="Edit quick actions">${SLIDERS_ICON}</button>`;
  container.appendChild(scroller);

  if (!handlers.has(container)) {
    container.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      const entry = handlers.get(container);
      if (!entry) return;
      if (target.closest('.quick-action-edit-chip')) {
        entry.onEdit();
        return;
      }
      const chip = target.closest<HTMLButtonElement>('.quick-action-chip');
      if (!chip || chip.disabled) return;
      const action = entry.actions.find((a) => a.id === chip.dataset.actionId);
      if (action) entry.onTap(action, chip);
    });
  }
  handlers.set(container, { actions, onTap, onEdit });
}

export function setQuickActionsBarDisabled(container: HTMLElement, disabled: boolean): void {
  container.classList.toggle('quick-actions-bar--disabled', disabled);
  for (const chip of container.querySelectorAll<HTMLButtonElement>('.quick-action-chip')) {
    chip.disabled = disabled;
  }
}
