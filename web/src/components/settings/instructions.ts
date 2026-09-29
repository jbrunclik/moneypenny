import { EDIT_ICON } from '../../utils/icons';
import { settings } from '../../api/settings';
import { toast } from '../Toast';
import type { UserSettings } from '../../types/api';
import { log, showSavedIndicator } from './shared';

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
 * Render the "AI Instructions" tab section.
 */
export function renderInstructionsSection(): string {
  const instructions = currentInstructions;
  const charCount = instructions.length;
  const charCountClass = charCount > CHAR_LIMIT ? 'error' : charCount > CHAR_LIMIT * 0.9 ? 'warning' : '';

  return `
      <div class="settings-section" data-settings-section="instructions">
      <div class="settings-section-title">AI Instructions</div>
      <div class="settings-field">
        <label class="settings-label settings-label-with-icon" for="custom-instructions">
          <span class="settings-label-icon">${EDIT_ICON}</span>
          Custom Instructions
        </label>
        <p class="settings-helper">Tell the AI how to respond (e.g., "respond in Czech", "be concise", "use bullet points")</p>
        <textarea
          id="custom-instructions"
          class="settings-textarea"
          placeholder="Enter your custom instructions here..."
          maxlength="${CHAR_LIMIT}"
        >${instructions}</textarea>
        <span class="settings-char-count ${charCountClass}">${charCount}/${CHAR_LIMIT}</span>
        <span class="settings-saved-indicator" data-saved-for="custom-instructions">Saved</span>
      </div>
      </div>
  `;
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
