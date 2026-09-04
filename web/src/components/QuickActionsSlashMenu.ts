/**
 * Slash menu: typing "/" in an empty composer (inside a program) lists the
 * quick actions, filtered by what follows the slash. Rendered inside the
 * composer pill above the textarea. Presentation only.
 */
import type { QuickAction } from '../types/api';
import { clearElement, escapeHtml } from '../utils/dom';

export function filterQuickActions(actions: QuickAction[], filter: string): QuickAction[] {
  const q = filter.trim().toLowerCase();
  if (!q) return actions;
  return actions.filter(
    (a) => a.label.toLowerCase().includes(q) || a.body.toLowerCase().includes(q)
  );
}

export function renderSlashMenu(
  container: HTMLElement,
  actions: QuickAction[],
  activeIndex: number,
  onPick: (action: QuickAction) => void
): void {
  clearElement(container);
  container.innerHTML = actions
    .map(
      (a, i) => `
      <button type="button" class="qa-slash-item${i === activeIndex ? ' active' : ''}" role="option" aria-selected="${i === activeIndex}" data-index="${i}">
        <span class="qa-slash-emoji" aria-hidden="true">${escapeHtml(a.emoji)}</span>
        <span class="qa-slash-label">${escapeHtml(a.label)}</span>
        <span class="qa-slash-body">${escapeHtml(a.body)}</span>
      </button>`
    )
    .join('');
  container.onclick = (e) => {
    const item = (e.target as HTMLElement).closest<HTMLElement>('.qa-slash-item');
    if (!item) return;
    const action = actions[Number(item.dataset.index)];
    if (action) onPick(action);
  };
  container.classList.toggle('hidden', actions.length === 0);
}

export function clearSlashMenu(container: HTMLElement): void {
  clearElement(container);
  container.onclick = null;
  container.classList.add('hidden');
}
