/**
 * Bottom action sheet (mobile) / centered menu (desktop): a list of actions
 * for one subject, replacing crammed multi-button swipe rows. One instance
 * at a time; backdrop tap and Escape dismiss.
 */
import { escapeHtml } from '../utils/dom';
import { hapticTick } from '../utils/haptics';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';

export interface SheetAction {
  label: string;
  icon: string;
  danger?: boolean;
  onSelect: () => void;
}

const SHEET_ID = 'action-sheet';

export function closeActionSheet(): void {
  document.getElementById(SHEET_ID)?.remove();
}

export function showActionSheet(title: string, actions: SheetAction[]): void {
  closeActionSheet();

  const overlay = document.createElement('div');
  overlay.id = SHEET_ID;
  overlay.className = 'action-sheet-overlay';
  overlay.innerHTML = `
    <div class="action-sheet" role="menu" aria-label="${escapeHtml(title)}">
      <div class="action-sheet-title">${escapeHtml(title)}</div>
      ${actions
        .map(
          (action, index) => `
        <button class="action-sheet-item${action.danger ? ' danger' : ''}" data-action-index="${index}" role="menuitem">
          <span class="action-sheet-icon">${action.icon}</span>
          <span>${escapeHtml(action.label)}</span>
        </button>`
        )
        .join('')}
      <button class="action-sheet-item action-sheet-cancel">Cancel</button>
    </div>
  `;

  overlay.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    if (target === overlay || target.closest('.action-sheet-cancel')) {
      closeActionSheet();
      return;
    }
    const item = target.closest<HTMLElement>('[data-action-index]');
    if (item) {
      const action = actions[Number(item.dataset.actionIndex)];
      closeActionSheet();
      action?.onSelect();
    }
  });

  document.body.appendChild(overlay);
  hapticTick();
}

// Escape dismisses the sheet (shares the central popup escape stack)
registerPopupEscapeHandler(SHEET_ID, closeActionSheet);
