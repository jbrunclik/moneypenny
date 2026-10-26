/**
 * Bottom action sheet (mobile) / centered menu (desktop): a list of actions
 * for one subject, replacing crammed multi-button swipe rows. One instance
 * at a time; backdrop tap and Escape dismiss.
 */
import { createElement } from '../utils/dom';
import { hapticTick } from '../utils/haptics';
import { createIconElement, type IconHtml } from '../utils/icons';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';
import { attachSheetDismiss } from '../utils/sheet-gesture';

export interface SheetAction {
  label: string;
  icon: IconHtml;
  danger?: boolean;
  onSelect: () => void;
}

const SHEET_ID = 'action-sheet';

function closeActionSheet(): void {
  document.getElementById(SHEET_ID)?.remove();
}

export function showActionSheet(title: string, actions: SheetAction[]): void {
  closeActionSheet();

  const overlay = document.createElement('div');
  overlay.id = SHEET_ID;
  overlay.className = 'action-sheet-overlay';
  const items = actions.map((action, index) =>
    createElement(
      'button',
      { class: `action-sheet-item${action.danger ? ' danger' : ''}`, 'data-action-index': String(index), role: 'menuitem' },
      [createIconElement('action-sheet-icon', action.icon), createElement('span', {}, [action.label])]
    )
  );
  overlay.appendChild(
    createElement('div', { class: 'action-sheet', role: 'menu', 'aria-label': title }, [
      createElement('div', { class: 'action-sheet-title' }, [title]),
      ...items,
      createElement('button', { class: 'action-sheet-item action-sheet-cancel' }, ['Cancel']),
    ])
  );

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
  const sheet = overlay.querySelector<HTMLElement>('.action-sheet');
  if (sheet) attachSheetDismiss(sheet, closeActionSheet);
  hapticTick();
}

// Escape dismisses the sheet (shares the central popup escape stack)
registerPopupEscapeHandler(SHEET_ID, closeActionSheet);
