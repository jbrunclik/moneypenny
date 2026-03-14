/**
 * Language Dashboard component.
 *
 * Renders the programs list view (cards) and the program chat header.
 * "New Program" opens a modal overlay with name + flag emoji picker.
 */

import type { LanguageProgram } from '../types/api';
import { showConfirm } from './Modal';
import { CLOSE_ICON, DELETE_ICON, PLAY_ICON, PLUS_ICON, REFRESH_ICON, LANGUAGE_ICON } from '../utils/icons';
import { escapeHtml } from '../utils/dom';

// ============================================================================
// Programs List View
// ============================================================================

/** Create the main language programs element (program list + "New Program" button). */
export function createLanguageProgramsElement(
  programs: LanguageProgram[],
  onAddProgram: (data: { name: string; emoji: string }) => void,
  onDeleteProgram: (id: string) => void,
  onSelectProgram: (id: string) => void,
): HTMLElement {
  const container = document.createElement('div');
  container.className = 'language-programs-container';

  const header = document.createElement('div');
  header.className = 'language-programs-header';
  header.innerHTML = `
    <div class="language-programs-title-row">
      <div class="language-programs-title">
        <span class="language-programs-title-icon">${LANGUAGE_ICON}</span>
        <h2>Language Learning</h2>
      </div>
      <div class="language-programs-actions">
        <button class="language-add-btn" title="New program">${PLUS_ICON}<span>New Program</span></button>
      </div>
    </div>
  `;
  container.appendChild(header);

  if (programs.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'language-empty-state';
    empty.innerHTML = `
      <p>No language programs yet.</p>
      <p class="language-empty-hint">Create a program to start learning with your AI tutor.</p>
    `;
    container.appendChild(empty);
  } else {
    const grid = document.createElement('div');
    grid.className = 'language-programs-grid';
    for (const program of programs) {
      grid.appendChild(createProgramCard(program, onDeleteProgram, onSelectProgram));
    }
    container.appendChild(grid);
  }

  // "New Program" button opens modal (pass existing names to filter dropdown)
  const existingNames = new Set(programs.map((p) => p.name.toLowerCase()));
  header.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('.language-add-btn')) {
      showNewProgramModal(onAddProgram, existingNames);
    }
  });

  return container;
}

function createProgramCard(
  program: LanguageProgram,
  onDelete: (id: string) => void,
  onSelect: (id: string) => void,
): HTMLElement {
  const card = document.createElement('div');
  card.className = 'language-program-card';
  card.dataset.programId = program.id;

  card.innerHTML = `
    <div class="language-card-header">
      <span class="language-card-emoji">${escapeHtml(program.emoji)}</span>
      <span class="language-card-name">${escapeHtml(program.name)}</span>
      <div class="language-card-actions">
        <button class="btn-icon language-card-continue" title="Continue learning">${PLAY_ICON}<span class="language-card-action-label">Continue</span></button>
        <button class="btn-icon language-card-delete" title="Delete program">${DELETE_ICON}</button>
      </div>
    </div>
  `;

  card.addEventListener('click', async (e) => {
    const target = e.target as HTMLElement;
    if (target.closest('.language-card-delete')) {
      e.stopPropagation();
      const confirmed = await showConfirm({
        title: 'Delete Program',
        message: `Delete "${program.name}"? This will also delete the conversation and all learning data.`,
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

/** Predefined languages with flag emoji + name. */
const LANGUAGES: { emoji: string; name: string }[] = [
  { emoji: '\uD83C\uDDEC\uD83C\uDDE7', name: 'English' },
  { emoji: '\uD83C\uDDEA\uD83C\uDDF8', name: 'Spanish' },
  { emoji: '\uD83C\uDDEB\uD83C\uDDF7', name: 'French' },
  { emoji: '\uD83C\uDDE9\uD83C\uDDEA', name: 'German' },
  { emoji: '\uD83C\uDDEE\uD83C\uDDF9', name: 'Italian' },
  { emoji: '\uD83C\uDDF5\uD83C\uDDF9', name: 'Portuguese' },
  { emoji: '\uD83C\uDDEF\uD83C\uDDF5', name: 'Japanese' },
  { emoji: '\uD83C\uDDF0\uD83C\uDDF7', name: 'Korean' },
  { emoji: '\uD83C\uDDE8\uD83C\uDDF3', name: 'Chinese' },
  { emoji: '\uD83C\uDDF7\uD83C\uDDFA', name: 'Russian' },
  { emoji: '\uD83C\uDDF3\uD83C\uDDF1', name: 'Dutch' },
  { emoji: '\uD83C\uDDF5\uD83C\uDDF1', name: 'Polish' },
  { emoji: '\uD83C\uDDF8\uD83C\uDDEA', name: 'Swedish' },
  { emoji: '\uD83C\uDDF9\uD83C\uDDF7', name: 'Turkish' },
  { emoji: '\uD83C\uDDE8\uD83C\uDDFF', name: 'Czech' },
  { emoji: '\uD83C\uDDEC\uD83C\uDDF7', name: 'Greek' },
  { emoji: '\uD83C\uDDEE\uD83C\uDDF3', name: 'Hindi' },
  { emoji: '\uD83C\uDDF9\uD83C\uDDED', name: 'Thai' },
  { emoji: '\uD83C\uDDFB\uD83C\uDDF3', name: 'Vietnamese' },
  { emoji: '\uD83C\uDDE6\uD83C\uDDEA', name: 'Arabic' },
  { emoji: '\uD83C\uDDEE\uD83C\uDDF1', name: 'Hebrew' },
  { emoji: '\uD83C\uDDFA\uD83C\uDDE6', name: 'Ukrainian' },
  { emoji: '\uD83C\uDDED\uD83C\uDDFA', name: 'Hungarian' },
  { emoji: '\uD83C\uDDEB\uD83C\uDDEE', name: 'Finnish' },
  { emoji: '\uD83C\uDDE9\uD83C\uDDF0', name: 'Danish' },
  { emoji: '\uD83C\uDDF3\uD83C\uDDF4', name: 'Norwegian' },
  { emoji: '\uD83C\uDDF7\uD83C\uDDF4', name: 'Romanian' },
  { emoji: '\uD83C\uDDEE\uD83C\uDDE9', name: 'Indonesian' },
];

function showNewProgramModal(
  onAdd: (data: { name: string; emoji: string }) => void,
  existingNames: Set<string> = new Set(),
): void {
  const overlay = document.createElement('div');
  overlay.className = 'language-modal-overlay';

  const modal = document.createElement('div');
  modal.className = 'language-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');

  const availableLanguages = LANGUAGES.filter((lang) => !existingNames.has(lang.name.toLowerCase()));
  const optionsHtml = availableLanguages.map(
    (lang) => `<option value="${escapeHtml(lang.name)}" data-emoji="${escapeHtml(lang.emoji)}">${lang.emoji} ${escapeHtml(lang.name)}</option>`,
  ).join('');

  modal.innerHTML = `
    <div class="language-modal-header">
      <div class="language-modal-title-row">
        <span class="language-modal-icon">${LANGUAGE_ICON}</span>
        <h2>New Program</h2>
      </div>
      <button class="language-modal-close" title="Close">${CLOSE_ICON}</button>
    </div>
    <div class="language-modal-body">
      <select class="language-select">
        <option value="" disabled selected>Choose a language...</option>
        ${optionsHtml}
      </select>
    </div>
    <div class="language-modal-footer">
      <button class="language-modal-cancel">Cancel</button>
      <button class="language-add-submit" disabled>Create</button>
    </div>
  `;

  overlay.appendChild(modal);

  const handleKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') close();
  };

  const close = () => {
    document.removeEventListener('keydown', handleKeydown);
    overlay.classList.add('language-modal-exit');
    setTimeout(() => overlay.remove(), 150);
  };

  modal.querySelector('.language-modal-close')!.addEventListener('click', close);
  modal.querySelector('.language-modal-cancel')!.addEventListener('click', close);

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  document.addEventListener('keydown', handleKeydown);

  // Enable submit when a language is selected
  const select = modal.querySelector('.language-select') as HTMLSelectElement;
  const submitBtn = modal.querySelector('.language-add-submit') as HTMLButtonElement;

  select.addEventListener('change', () => {
    submitBtn.disabled = !select.value;
  });

  submitBtn.addEventListener('click', () => {
    const selectedOption = select.selectedOptions[0];
    if (!selectedOption || !select.value) return;

    const name = select.value;
    const emoji = selectedOption.dataset.emoji || LANGUAGES[0].emoji;
    onAdd({ name, emoji });
    close();
  });

  document.body.appendChild(overlay);
  requestAnimationFrame(() => select.focus());
}

// ============================================================================
// Program Chat Header
// ============================================================================

/** Create the header above a program's chat (back arrow, name, reset button). */
export function createLanguageProgramHeader(
  program: LanguageProgram,
  onBack: () => void,
  onReset: () => void,
): HTMLElement {
  const header = document.createElement('div');
  header.className = 'language-program-header';
  header.innerHTML = `
    <button class="language-back-btn" title="Back to programs">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
        <polyline points="15,18 9,12 15,6"/>
      </svg>
    </button>
    <span class="language-program-header-emoji">${escapeHtml(program.emoji)}</span>
    <span class="language-program-header-name">${escapeHtml(program.name)}</span>
    <button class="language-reset-btn" title="Start a new lesson">${REFRESH_ICON}<span>New Lesson</span></button>
  `;

  header.addEventListener('click', async (e) => {
    const target = e.target as HTMLElement;
    if (target.closest('.language-back-btn')) {
      onBack();
      return;
    }
    if (target.closest('.language-reset-btn')) {
      const confirmed = await showConfirm({
        title: 'New Lesson',
        message: 'Start a new lesson? The current conversation will be cleared. Your vocabulary and assessment data will be kept.',
        confirmLabel: 'Start New',
        danger: false,
      });
      if (confirmed) onReset();
    }
  });

  return header;
}

// ============================================================================
// Loading State
// ============================================================================

export function createLanguageLoadingElement(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'language-loading';
  el.innerHTML = '<div class="language-loading-spinner"></div><p>Loading language programs...</p>';
  return el;
}
