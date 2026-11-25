/**
 * Sharing a project: who has access (the owner first), each family member
 * with Add or Remove. The sheet stays open and a row flips in place once its
 * change went through. Bottom sheet on mobile, centered on desktop (the
 * action sheet's shell); backdrop, Done and Escape close it.
 */
import type { Person } from '../types/api';
import { createUserAvatarElement } from '../utils/avatar';
import { createElement } from '../utils/dom';
import { hapticTick } from '../utils/haptics';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';
import { attachSheetDismiss } from '../utils/sheet-gesture';

export interface ShareSheetOptions {
  projectName: string;
  owner: { name: string; picture?: string | null | undefined };
  /** The family members the project can be shared with (everyone but the owner) */
  people: Person[];
  memberIds: Set<string>;
  /** Resolve true once the change went through (false: declined or failed, row unchanged) */
  onAdd: (person: Person) => Promise<boolean>;
  onRemove: (person: Person) => Promise<boolean>;
}

const SHEET_ID = 'share-sheet';

function closeShareSheet(): void {
  document.getElementById(SHEET_ID)?.remove();
}

function personRow(name: string, picture: string | null | undefined, status: string | null, action?: HTMLElement): HTMLElement {
  return createElement('div', { class: 'share-sheet-row' }, [
    createUserAvatarElement(picture ?? undefined, name, 'share-sheet-avatar'),
    createElement('div', { class: 'share-sheet-text' }, [
      createElement('span', { class: 'share-sheet-name' }, [name]),
      status ? createElement('span', { class: 'share-sheet-status' }, [status]) : null,
    ]),
    action ?? null,
  ]);
}

function memberRow(person: Person, options: ShareSheetOptions): HTMLElement {
  const isMember = options.memberIds.has(person.id);
  const button = createElement(
    'button',
    { type: 'button', class: `btn btn-sm share-sheet-action ${isMember ? 'btn-secondary' : 'share-sheet-action--add'}` },
    [isMember ? 'Remove' : 'Add']
  );
  const row = personRow(person.name, person.picture, isMember ? 'Has access' : null, button);
  button.addEventListener('click', () => {
    button.disabled = true;
    const change = isMember ? options.onRemove(person) : options.onAdd(person);
    void change
      .catch(() => false)
      .then((done) => {
        if (!done) {
          button.disabled = false;
          return;
        }
        if (isMember) options.memberIds.delete(person.id);
        else options.memberIds.add(person.id);
        row.replaceWith(memberRow(person, options));
      });
  });
  return row;
}

export function openShareSheet(options: ShareSheetOptions): void {
  closeShareSheet();
  const overlay = createElement('div', { id: SHEET_ID, class: 'action-sheet-overlay' });
  const title = `Share “${options.projectName}”`;
  overlay.appendChild(
    createElement('div', { class: 'action-sheet share-sheet', role: 'dialog', 'aria-label': title }, [
      createElement('h4', { class: 'share-sheet-title' }, [title]),
      createElement('p', { class: 'share-sheet-hint' }, [
        'People you add share its instructions, memory and documents and get a notification. Everyone’s chats stay their own.',
      ]),
      createElement('div', { class: 'share-sheet-list' }, [
        personRow(`${options.owner.name} (you)`, options.owner.picture, 'Owner'),
        ...options.people.map((person) => memberRow(person, options)),
      ]),
      createElement('button', { type: 'button', class: 'action-sheet-item action-sheet-cancel share-sheet-done' }, [
        'Done',
      ]),
    ])
  );
  overlay.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    if (target === overlay || target.closest('.share-sheet-done')) closeShareSheet();
  });
  document.body.appendChild(overlay);
  const sheet = overlay.querySelector<HTMLElement>('.share-sheet');
  if (sheet) attachSheetDismiss(sheet, closeShareSheet);
  hapticTick();
}

// Escape closes the sheet (the central popup escape stack)
registerPopupEscapeHandler(SHEET_ID, closeShareSheet);
