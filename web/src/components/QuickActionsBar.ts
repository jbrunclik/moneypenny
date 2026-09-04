/**
 * Quick-actions chip bar: horizontally scrolling row of one-tap prompts
 * rendered above the composer in program conversations. Presentation only;
 * core/quick-actions.ts decides when it is mounted/visible and what a tap does.
 */
import type { QuickAction } from '../types/api';
import { clearElement, escapeHtml } from '../utils/dom';

type TapHandler = (action: QuickAction, chip: HTMLElement) => void;

// One delegated listener per container; re-renders swap the handler.
const handlers = new WeakMap<HTMLElement, { actions: QuickAction[]; onTap: TapHandler }>();

export function renderQuickActionsBar(
  container: HTMLElement,
  actions: QuickAction[],
  onTap: TapHandler
): void {
  clearElement(container);
  const scroller = document.createElement('div');
  scroller.className = 'quick-actions-scroller';
  scroller.innerHTML = actions
    .map(
      (a) => `
      <button type="button" class="quick-action-chip" data-action-id="${escapeHtml(a.id)}" title="${escapeHtml(a.body)}">
        <span class="quick-action-chip-emoji" aria-hidden="true">${escapeHtml(a.emoji)}</span>
        <span class="quick-action-chip-label">${escapeHtml(a.label)}</span>
      </button>`
    )
    .join('');
  container.appendChild(scroller);

  if (!handlers.has(container)) {
    container.addEventListener('click', (e) => {
      const chip = (e.target as HTMLElement).closest<HTMLButtonElement>('.quick-action-chip');
      if (!chip || chip.disabled) return;
      const entry = handlers.get(container);
      const action = entry?.actions.find((a) => a.id === chip.dataset.actionId);
      if (entry && action) entry.onTap(action, chip);
    });
  }
  handlers.set(container, { actions, onTap });
}

export function setQuickActionsBarDisabled(container: HTMLElement, disabled: boolean): void {
  container.classList.toggle('quick-actions-bar--disabled', disabled);
  for (const chip of container.querySelectorAll<HTMLButtonElement>('.quick-action-chip')) {
    chip.disabled = disabled;
  }
}
