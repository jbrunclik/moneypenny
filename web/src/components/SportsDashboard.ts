/**
 * Sports Dashboard component.
 *
 * Renders the programs list view (cards) and the program chat header.
 * "New Program" opens a modal overlay similar to Agent Editor.
 */

import type { SportsProgram } from '../types/api';
import { showConfirm } from './Modal';
import { CLEAR_ICON, CLOSE_ICON, DELETE_ICON, PLAY_ICON, PLUS_ICON, SPORTS_ICON } from '../utils/icons';
import { escapeHtml } from '../utils/dom';
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
  header.innerHTML = `
    <div class="sports-programs-title-row">
      <div class="sports-programs-title">
        <span class="sports-programs-title-icon">${SPORTS_ICON}</span>
        <h2>Sports Training</h2>
      </div>
      <div class="sports-programs-actions">
        <button class="sports-add-btn" title="New program">${PLUS_ICON}<span>New Program</span></button>
      </div>
    </div>
  `;
  container.appendChild(header);

  if (programs.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'sports-empty-state';
    empty.innerHTML = `
      <p>No training programs yet.</p>
      <p class="sports-empty-hint">Create a program to start training with your AI coach.</p>
    `;
    container.appendChild(empty);
  } else {
    const grid = document.createElement('div');
    grid.className = 'sports-programs-grid';
    for (const program of programs) {
      grid.appendChild(createProgramCard(program, onDeleteProgram, onSelectProgram));
    }
    container.appendChild(grid);
  }

  // "New Program" button opens modal
  header.addEventListener('click', (e) => {
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

  card.innerHTML = `
    <div class="sports-card-header">
      <span class="sports-card-emoji">${escapeHtml(program.emoji)}</span>
      <span class="sports-card-name">${escapeHtml(program.name)}</span>
      <div class="sports-card-actions">
        <button class="btn-icon sports-card-continue" title="Continue training">${PLAY_ICON}<span class="sports-card-action-label">Continue</span></button>
        <button class="btn-icon sports-card-delete" title="Delete program">${DELETE_ICON}</button>
      </div>
    </div>
  `;

  card.addEventListener('click', async (e) => {
    const target = e.target as HTMLElement;
    if (target.closest('.sports-card-delete')) {
      e.stopPropagation();
      const confirmed = await showConfirm({
        title: 'Delete Program',
        message: `Delete "${program.name}"? This will also delete the conversation and all training data.`,
        confirmLabel: 'Delete',
        danger: true,
      });
      if (confirmed) onDelete(program.id);
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
  let selectedEmoji = SPORTS_EMOJIS[0];

  // Create overlay
  const overlay = document.createElement('div');
  overlay.className = 'sports-modal-overlay';

  const modal = document.createElement('div');
  modal.className = 'sports-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');

  modal.innerHTML = `
    <div class="sports-modal-header">
      <div class="sports-modal-title-row">
        <span class="sports-modal-icon">${SPORTS_ICON}</span>
        <h2>New Program</h2>
      </div>
      <button class="sports-modal-close" title="Close">${CLOSE_ICON}</button>
    </div>
    <div class="sports-modal-body">
      <div class="sports-add-input-row">
        <div class="sports-emoji-wrapper">
          <button type="button" class="sports-emoji-trigger" title="Choose icon">${selectedEmoji}</button>
          <div class="sports-emoji-popover">
            <div class="sports-emoji-grid"></div>
          </div>
        </div>
        <input type="text" class="sports-add-name" placeholder="Program name" maxlength="100" />
      </div>
    </div>
    <div class="sports-modal-footer">
      <button class="sports-modal-cancel">Cancel</button>
      <button class="sports-add-submit">Create</button>
    </div>
  `;

  overlay.appendChild(modal);

  // Populate emoji grid
  const emojiGrid = modal.querySelector('.sports-emoji-grid')!;
  for (const emoji of SPORTS_EMOJIS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sports-emoji-option';
    btn.textContent = emoji;
    btn.dataset.emoji = emoji;
    emojiGrid.appendChild(btn);
  }

  const close = () => {
    overlay.classList.add('sports-modal-exit');
    setTimeout(() => overlay.remove(), 150);
  };

  // Close button
  modal.querySelector('.sports-modal-close')!.addEventListener('click', close);
  modal.querySelector('.sports-modal-cancel')!.addEventListener('click', close);

  // Close on overlay click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  // Close on Escape
  const handleKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      close();
      document.removeEventListener('keydown', handleKeydown);
    }
  };
  document.addEventListener('keydown', handleKeydown);

  // Emoji trigger
  const emojiTrigger = modal.querySelector('.sports-emoji-trigger') as HTMLButtonElement;
  const emojiPopover = modal.querySelector('.sports-emoji-popover') as HTMLDivElement;

  emojiTrigger.addEventListener('click', (e) => {
    e.stopPropagation();
    emojiPopover.classList.toggle('open');
  });

  emojiGrid.addEventListener('click', (e) => {
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
  modal.querySelector('.sports-add-submit')!.addEventListener('click', () => {
    const name = nameInput.value.trim();
    if (!name) {
      log.warn('Missing required fields for add program');
      nameInput.focus();
      return;
    }
    onAdd({ name, emoji: selectedEmoji });
    close();
    document.removeEventListener('keydown', handleKeydown);
  });

  document.body.appendChild(overlay);

  // Auto-focus name input
  requestAnimationFrame(() => nameInput.focus());
}

// ============================================================================
// Program Chat Header
// ============================================================================

/** Create the header above a program's chat (back arrow, name, reset button). */
export function createSportsProgramHeader(
  program: SportsProgram,
  onBack: () => void,
  onReset: () => void,
): HTMLElement {
  const header = document.createElement('div');
  header.className = 'sports-program-header';
  header.innerHTML = `
    <button class="sports-back-btn" title="Back to programs">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
        <polyline points="15,18 9,12 15,6"/>
      </svg>
    </button>
    <span class="sports-program-header-emoji">${escapeHtml(program.emoji)}</span>
    <span class="sports-program-header-name">${escapeHtml(program.name)}</span>
    <button class="sports-reset-btn" title="Reset conversation">${CLEAR_ICON}<span>Reset</span></button>
  `;

  header.addEventListener('click', async (e) => {
    const target = e.target as HTMLElement;
    if (target.closest('.sports-back-btn')) {
      onBack();
      return;
    }
    if (target.closest('.sports-reset-btn')) {
      const confirmed = await showConfirm({
        title: 'Reset Conversation',
        message: 'Reset this conversation? All messages will be deleted. Your goals and progress data will be kept.',
        confirmLabel: 'Reset',
        danger: true,
      });
      if (confirmed) onReset();
    }
  });

  return header;
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
