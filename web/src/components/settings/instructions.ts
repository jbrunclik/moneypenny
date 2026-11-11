import { CUSTOM_INSTRUCTIONS_MAX_CHARS, INSTRUCTIONS_REVIEW_PHASES } from '../../config';
import { clearElement, createElement } from '../../utils/dom';
import { EDIT_ICON, SPARKLES_ICON, iconNodes } from '../../utils/icons';
import { instructionsReview, settings } from '../../api/settings';
import { renderSetupReview, type ReviewTexts } from '../QuickActionsReview';
import type { SetupSuggestion } from '../../types/api';
import { toast } from '../Toast';
import { useStore } from '../../state/store';
import { fieldLabel, helper, log, showSavedIndicator } from './shared';

const CHAR_LIMIT = CUSTOM_INSTRUCTIONS_MAX_CHARS;

const REVIEW_TEXTS: ReviewTexts = {
  empty: 'Nothing to change - your instructions and memories match how you use them.',
  phases: INSTRUCTIONS_REVIEW_PHASES,
  back: 'Done',
};

/** The saved custom instructions (store: settings slice). */
function savedInstructions(): string {
  return useStore.getState().userSettings?.custom_instructions || '';
}

/**
 * The "AI Instructions" tab section.
 */
export function renderInstructionsSection(): HTMLElement {
  const instructions = savedInstructions();
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
      // Suggested changes from the user's recent chats, accepted one by one
      createElement('div', { class: 'settings-instructions-review-row' }, [
        createElement('button', { type: 'button', class: 'settings-instructions-review' }, [
          iconNodes(SPARKLES_ICON),
          'Review',
        ]),
        helper('Suggests changes from your recent chats and memories - you accept or reject each.', true),
      ]),
      createElement('div', { class: 'settings-instructions-review-panel' }),
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

let saving: Promise<void> | null = null;

/** Save the field if it changed; a save already running is shared (blur + Review click). */
function saveCustomInstructions(): Promise<void> {
  saving ??= saveNow().finally(() => {
    saving = null;
  });
  return saving;
}

async function saveNow(): Promise<void> {
  const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement | null;
  if (!textarea) return;
  const instructions = textarea.value.trim();
  if (instructions === savedInstructions()) return;

  try {
    await settings.update({ custom_instructions: instructions });
    useStore.getState().patchUserSettings({ custom_instructions: instructions });
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
    document
      .querySelector('.settings-instructions-review')
      ?.addEventListener('click', () => void startReview(textarea));
    // NOTE: no autofocus here - focusing this last field scrolled the
    // popup body to the bottom on open (regression test in settings.spec)
  }
}

/**
 * Settings' instructions Review: typing not yet saved is saved first, then
 * the suggestions render under the field; an accepted change lands in the
 * textarea, the counter and the store.
 */
async function startReview(textarea: HTMLTextAreaElement): Promise<void> {
  const row = document.querySelector<HTMLElement>('.settings-instructions-review-row');
  const button = document.querySelector<HTMLButtonElement>('.settings-instructions-review');
  const panel = document.querySelector<HTMLElement>('.settings-instructions-review-panel');
  if (!row || !button || !panel) return;
  await saveCustomInstructions();
  row.hidden = true;
  button.hidden = true;
  const applied = (text: string): void => {
    textarea.value = text;
    updateCharCount(textarea);
    useStore.getState().patchUserSettings({ custom_instructions: text });
  };
  const close = (): void => {
    clearElement(panel);
    row.hidden = false;
    button.hidden = false;
  };
  const handlers = {
    load: () => instructionsReview.review(),
    apply: (suggestion: SetupSuggestion) => instructionsReview.apply(suggestion),
    reject: (suggestion: SetupSuggestion) => instructionsReview.reject(suggestion),
  };
  renderSetupReview<string>(panel, handlers, applied, close, REVIEW_TEXTS);
}
