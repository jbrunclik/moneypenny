import { createElement } from '../../utils/dom';
import { EDIT_ICON } from '../../utils/icons';
import { settings } from '../../api/settings';
import { toast } from '../Toast';
import type { UserSettings } from '../../types/api';
import { fieldLabel, helper, log, showSavedIndicator } from './shared';

const CHAR_LIMIT = 2000;

/** Current custom instructions value */
let currentInstructions = '';

/** Adopt the server-side custom instructions after a settings fetch. */
export function loadInstructionsSettings(data: UserSettings): void {
  currentInstructions = data.custom_instructions || '';
}

export function getInstructionsLength(): number {
  return currentInstructions.length;
}

/**
 * The "AI Instructions" tab section.
 */
export function renderInstructionsSection(): HTMLElement {
  const instructions = currentInstructions;
  const charCount = instructions.length;
  const charCountClass = charCount > CHAR_LIMIT ? 'error' : charCount > CHAR_LIMIT * 0.9 ? 'warning' : '';
  const textarea = createElement('textarea', {
    id: 'custom-instructions',
    class: 'settings-textarea',
    placeholder: 'Enter your custom instructions here...',
    maxlength: String(CHAR_LIMIT),
  });
  textarea.textContent = instructions;

  return createElement('div', { class: 'settings-section', 'data-settings-section': 'instructions' }, [
    createElement('div', { class: 'settings-section-title' }, ['AI Instructions']),
    createElement('div', { class: 'settings-field' }, [
      fieldLabel(EDIT_ICON, 'Custom Instructions', 'custom-instructions'),
      helper('Tell the AI how to respond (e.g., "respond in Czech", "be concise", "use bullet points")'),
      textarea,
      createElement('span', { class: `settings-char-count ${charCountClass}` }, [`${charCount}/${CHAR_LIMIT}`]),
      createElement('span', { class: 'settings-saved-indicator', 'data-saved-for': 'custom-instructions' }, ['Saved']),
    ]),
  ]);
}

/**
 * Update character count display
 */
function updateCharCount(textarea: HTMLTextAreaElement): void {
  const charCount = textarea.value.length;
  const charCountEl = document.querySelector('.settings-char-count');
  if (charCountEl) {
    charCountEl.textContent = `${charCount}/${CHAR_LIMIT}`;
    charCountEl.className = 'settings-char-count';
    if (charCount > CHAR_LIMIT) {
      charCountEl.classList.add('error');
    } else if (charCount > CHAR_LIMIT * 0.9) {
      charCountEl.classList.add('warning');
    }
  }
}

/**
 * Save the custom instructions field (called on blur when changed).
 */
async function saveCustomInstructions(): Promise<void> {
  const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement | null;
  if (!textarea) return;
  const instructions = textarea.value.trim();
  if (instructions === currentInstructions) return;

  try {
    await settings.update({ custom_instructions: instructions });
    currentInstructions = instructions;
    showSavedIndicator('custom-instructions');
    log.info('Custom instructions saved', { length: instructions.length });
  } catch (error) {
    log.error('Failed to save custom instructions', { error });
    toast.error('Failed to save custom instructions');
  }
}

/** Attach the textarea's live char count and save-on-blur after the body renders. */
export function bindInstructionsField(): void {
  const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement;
  if (textarea) {
    textarea.addEventListener('input', () => updateCharCount(textarea));
    textarea.addEventListener('blur', () => void saveCustomInstructions());
    // NOTE: no autofocus here - focusing this last field scrolled the
    // popup body to the bottom on open (regression test in settings.spec)
  }
}
