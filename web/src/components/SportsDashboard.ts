/**
 * Sports Dashboard component.
 *
 * Renders the programs list view (cards) and the program chat header.
 * "New Program" opens a modal overlay similar to Agent Editor.
 */

import type { SportsProgram } from '../types/api';
import { showConfirm } from './Modal';
import { renderChatHeader } from './ChatHeader';
import {
  CLEAR_ICON,
  CLOSE_ICON,
  DELETE_ICON,
  PLAY_ICON,
  PLUS_ICON,
  SLIDERS_ICON,
  SPORTS_ICON,
  createIconButton,
  createIconElement,
  setIcon,
} from '../utils/icons';
import { createElement } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import { createEmptyState } from './EmptyState';
import { createLogger } from '../utils/logger';

const log = createLogger('SportsDashboard');

// ============================================================================
// Programs List View
// ============================================================================

/** Create the main sports programs element (program list + "New Program" button). */
export function createSportsProgramsElement(
  programs: SportsProgram[],
  onAddProgram: (data: { name: string; emoji: string }) => void,
  onDeleteProgram: (id: string) => void,
  onSelectProgram: (id: string) => void,
): HTMLElement {
  const container = document.createElement('div');
  container.className = 'sports-programs-container';

  const header = document.createElement('div');
  header.className = 'sports-programs-header';
  const titleRow = createElement('div', { class: 'sports-programs-title-row' }, [
    createElement('div', { class: 'sports-programs-title' }, [
      createIconElement('sports-programs-title-icon', SPORTS_ICON),
      createElement('h2', {}, ['Sports Training']),
    ]),
  ]);
  // Empty: the empty state's "Create your first program" is the only
  // create button (a header twin did the same thing)
  if (programs.length > 0) {
    const addBtn = createElement('button', { class: 'sports-add-btn', title: 'New program' });
    setIcon(addBtn, PLUS_ICON);
    addBtn.append(createElement('span', {}, ['New Program']));
    titleRow.appendChild(createElement('div', { class: 'sports-programs-actions' }, [addBtn]));
  }
  header.appendChild(titleRow);
  container.appendChild(header);

  if (programs.length === 0) {
    const cta = createElement('button', { class: 'sports-add-btn program-empty-cta' });
    setIcon(cta, PLUS_ICON);
    cta.append(createElement('span', {}, ['Create your first program']));
    container.appendChild(createEmptyState({
      icon: SPORTS_ICON,
      title: 'No training programs yet',
      hint: 'Create a program to start training with your AI coach.',
      cta,
      className: 'sports-empty-state',
    }));
  } else {
    const grid = document.createElement('div');
    grid.className = 'sports-programs-grid';
    for (const program of programs) {
      grid.appendChild(createProgramCard(program, onDeleteProgram, onSelectProgram));
    }
    container.appendChild(grid);
  }

  // "New Program" buttons (header + empty-state CTA) open the modal
  container.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('.sports-add-btn')) {
      showNewProgramModal(onAddProgram);
    }
  });

  return container;
}

function createProgramCard(
  program: SportsProgram,
  onDelete: (id: string) => void,
  onSelect: (id: string) => void,
): HTMLElement {
  const card = document.createElement('div');
  card.className = 'sports-program-card';
  card.dataset.programId = program.id;

  const continueBtn = createElement('button', { class: 'btn-icon sports-card-continue', title: 'Continue training' });
  setIcon(continueBtn, PLAY_ICON);
  continueBtn.append(createElement('span', { class: 'sports-card-action-label' }, ['Continue']));
  const deleteBtn = createElement('button', { class: 'btn-icon sports-card-delete', title: 'Delete program' });
  setIcon(deleteBtn, DELETE_ICON);
  card.appendChild(
    createElement('div', { class: 'sports-card-header' }, [
      createElement('span', { class: 'sports-card-emoji' }, [program.emoji]),
      createElement('span', { class: 'sports-card-name' }, [program.name]),
      createElement('div', { class: 'sports-card-actions' }, [continueBtn, deleteBtn]),
    ])
  );

  const confirmDelete = async (): Promise<void> => {
    const confirmed = await showConfirm({
      title: 'Delete Program',
      message: `Delete "${program.name}"? This will also delete the conversation and all training data.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (confirmed) onDelete(program.id);
  };
  card.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    if (target.closest('.sports-card-delete')) {
      e.stopPropagation();
      void confirmDelete();
      return;
    }
    onSelect(program.id);
  });

  return card;
}

// ============================================================================
// New Program Modal
// ============================================================================

/** Sports-relevant emoji options for the picker. */
const SPORTS_EMOJIS = [
  '\uD83D\uDCAA', '\uD83C\uDFC3', '\uD83D\uDEB4', '\uD83C\uDFCA', '\u26BD',
  '\uD83C\uDFC0', '\uD83C\uDFBE', '\uD83E\uDD4A', '\uD83E\uDDD8', '\uD83C\uDFCB',
  '\u26F7\uFE0F', '\uD83D\uDEB5', '\uD83E\uDD3E', '\uD83C\uDFC7', '\uD83E\uDD3C',
  '\uD83C\uDFAF', '\uD83C\uDFF8', '\uD83E\uDD45', '\uD83C\uDFC4', '\uD83E\uDD38',
  '\uD83C\uDFCC', '\u26F3', '\uD83E\uDD3D', '\uD83C\uDFAF', '\u2764\uFE0F',
];

function showNewProgramModal(onAdd: (data: { name: string; emoji: string }) => void): void {
  let selectedEmoji = SPORTS_EMOJIS[0] ?? '';

  // Create overlay
  const overlay = document.createElement('div');
  overlay.className = 'sports-modal-overlay';

  const modal = document.createElement('div');
  modal.className = 'sports-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');

  modal.append(
    createElement('div', { class: 'sports-modal-header' }, [
      createElement('div', { class: 'sports-modal-title-row' }, [
        createIconElement('sports-modal-icon', SPORTS_ICON),
        createElement('h2', { class: 'dialog-title' }, ['New Program']),
      ]),
      createIconButton({ class: 'sports-modal-close dialog-close', title: 'Close', 'aria-label': 'Close' }, CLOSE_ICON),
    ]),
    createElement('div', { class: 'sports-modal-body' }, [
      createElement('div', { class: 'sports-add-input-row' }, [
        createElement('div', { class: 'sports-emoji-wrapper' }, [
          createElement('button', { type: 'button', class: 'sports-emoji-trigger', title: 'Choose icon' }, [
            selectedEmoji,
          ]),
          createElement('div', { class: 'sports-emoji-popover' }, [
            createElement('div', { class: 'sports-emoji-grid' }),
          ]),
        ]),
        createElement('input', { type: 'text', class: 'sports-add-name', placeholder: 'Program name', maxlength: '100' }),
      ]),
    ]),
    createElement('div', { class: 'sports-modal-footer' }, [
      createElement('button', { class: 'sports-modal-cancel' }, ['Cancel']),
      createElement('button', { class: 'sports-add-submit' }, ['Create']),
    ])
  );

  overlay.appendChild(modal);

  // Populate emoji grid
  const emojiGrid = modal.querySelector('.sports-emoji-grid');
  for (const emoji of SPORTS_EMOJIS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sports-emoji-option';
    btn.textContent = emoji;
    btn.dataset.emoji = emoji;
    emojiGrid?.appendChild(btn);
  }

  // Close on Escape
  const handleKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      close();
      return;
    }
    trapTabKey(modal, e);
  };

  const close = () => {
    document.removeEventListener('keydown', handleKeydown);
    overlay.classList.add('sports-modal-exit');
    setTimeout(() => overlay.remove(), 150);
  };

  // Close button
  modal.querySelector('.sports-modal-close')?.addEventListener('click', close);
  modal.querySelector('.sports-modal-cancel')?.addEventListener('click', close);

  // Close on overlay click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  document.addEventListener('keydown', handleKeydown);

  // Emoji trigger
  const emojiTrigger = modal.querySelector('.sports-emoji-trigger') as HTMLButtonElement;
  const emojiPopover = modal.querySelector('.sports-emoji-popover') as HTMLDivElement;

  emojiTrigger.addEventListener('click', (e) => {
    e.stopPropagation();
    emojiPopover.classList.toggle('open');
  });

  emojiGrid?.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    if (target.dataset.emoji) {
      selectedEmoji = target.dataset.emoji;
      emojiTrigger.textContent = selectedEmoji;
      emojiPopover.classList.remove('open');
    }
  });

  // Close popover on click outside
  modal.addEventListener('click', (e) => {
    const emojiWrapper = modal.querySelector('.sports-emoji-wrapper');
    if (emojiWrapper && !emojiWrapper.contains(e.target as Node)) {
      emojiPopover.classList.remove('open');
    }
  });

  // Submit
  const nameInput = modal.querySelector('.sports-add-name') as HTMLInputElement;
  modal.querySelector('.sports-add-submit')?.addEventListener('click', () => {
    const name = nameInput.value.trim();
    if (!name) {
      log.warn('Missing required fields for add program');
      nameInput.focus();
      return;
    }
    onAdd({ name, emoji: selectedEmoji });
    close();
  });

  document.body.appendChild(overlay);

  // Auto-focus name input
  requestAnimationFrame(() => nameInput.focus());
}

// ============================================================================
// Program Chat Header
// ============================================================================

/** Create the header above a program's chat (back arrow, name, quick actions, reset). */
export function renderSportsProgramHeader(
  program: SportsProgram,
  onBack: () => void,
  onReset: () => void,
  onQuickActions: () => void,
): void {
  const quickActionsBtn = document.createElement('button');
  quickActionsBtn.className = 'program-quick-actions-btn';
  quickActionsBtn.title = 'Quick actions';
  quickActionsBtn.setAttribute('aria-label', 'Edit quick actions');
  setIcon(quickActionsBtn, SLIDERS_ICON);
  quickActionsBtn.append(createElement('span', {}, ['Quick actions']));
  quickActionsBtn.addEventListener('click', onQuickActions);

  const resetBtn = document.createElement('button');
  resetBtn.className = 'sports-reset-btn';
  resetBtn.title = 'Reset conversation';
  setIcon(resetBtn, CLEAR_ICON);
  resetBtn.append(createElement('span', {}, ['Reset']));
  const confirmReset = async (): Promise<void> => {
    const confirmed = await showConfirm({
      title: 'Reset Conversation',
      message: 'Reset this conversation? All messages will be deleted. Your goals and progress data will be kept.',
      confirmLabel: 'Reset',
      danger: true,
    });
    if (confirmed) onReset();
  };
  resetBtn.addEventListener('click', () => {
    void confirmReset();
  });

  renderChatHeader({
    title: program.name,
    emoji: program.emoji,
    extraClass: 'sports-program-header',
    onBack,
    actions: [quickActionsBtn, resetBtn],
  });
}

// ============================================================================
// Loading State
// ============================================================================

export function createSportsLoadingElement(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'sports-loading';
  el.innerHTML = '<div class="sports-loading-spinner"></div><p>Loading sports programs...</p>';
  return el;
}
