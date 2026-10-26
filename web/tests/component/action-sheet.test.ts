import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { showActionSheet, type SheetAction } from '@/components/ActionSheet';
import { EDIT_ICON, DELETE_ICON } from '@/utils/icons';
import { destroyPopupEscapeListener, initPopupEscapeListener } from '@/utils/popupEscapeHandler';

const sheet = () => document.getElementById('action-sheet');
const items = () => [...document.querySelectorAll<HTMLElement>('.action-sheet-item[data-action-index]')];

function actions(): Array<SheetAction & { onSelect: ReturnType<typeof vi.fn> }> {
  return [
    { label: 'Rename', icon: EDIT_ICON, onSelect: vi.fn() },
    { label: 'Delete', icon: DELETE_ICON, danger: true, onSelect: vi.fn() },
  ];
}

describe('ActionSheet', () => {
  // Once: destroying the listener also drops the sheet's module-level registration
  beforeAll(() => initPopupEscapeListener());
  afterAll(() => destroyPopupEscapeListener());

  beforeEach(() => {
    document.body.replaceChildren();
  });

  it('lists the actions under the title, the dangerous one marked', () => {
    showActionSheet('Conversation', actions());

    expect(sheet()!.querySelector('.action-sheet')!.getAttribute('aria-label')).toBe('Conversation');
    expect(sheet()!.querySelector('.action-sheet-title')!.textContent).toBe('Conversation');
    expect(items().map((i) => i.querySelector('span:last-child')!.textContent)).toEqual(['Rename', 'Delete']);
    expect(items().map((i) => i.classList.contains('danger'))).toEqual([false, true]);
  });

  it('closes before running the chosen action', () => {
    const list = actions();
    list[1]!.onSelect.mockImplementation(() => expect(sheet()).toBeNull());
    showActionSheet('Conversation', list);

    items()[1]!.click();

    expect(list[1]!.onSelect).toHaveBeenCalledOnce();
    expect(list[0]!.onSelect).not.toHaveBeenCalled();
  });

  it('dismisses on Cancel and on a backdrop tap without running anything', () => {
    const list = actions();
    showActionSheet('Conversation', list);
    document.querySelector<HTMLElement>('.action-sheet-cancel')!.click();
    expect(sheet()).toBeNull();

    showActionSheet('Conversation', list);
    sheet()!.click();
    expect(sheet()).toBeNull();

    expect(list.every((a) => a.onSelect.mock.calls.length === 0)).toBe(true);
  });

  it('a tap inside the sheet (the title) keeps it open', () => {
    showActionSheet('Conversation', actions());
    document.querySelector<HTMLElement>('.action-sheet-title')!.click();
    expect(sheet()).not.toBeNull();
  });

  it('dismisses on Escape', () => {
    showActionSheet('Conversation', actions());
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(sheet()).toBeNull();
  });

  it('shows one sheet at a time', () => {
    showActionSheet('First', actions());
    showActionSheet('Second', actions());

    expect(document.querySelectorAll('#action-sheet')).toHaveLength(1);
    expect(sheet()!.querySelector('.action-sheet-title')!.textContent).toBe('Second');
  });
});
