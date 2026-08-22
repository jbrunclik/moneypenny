/**
 * Inline editing of a sent user message: the bubble content swaps for a
 * textarea with Save & Resend / Cancel. Saving is handled by core/messaging
 * (truncate the tail server-side, resend the edited text).
 */

export interface InlineEditCallbacks {
  onSave: (newText: string) => void;
}

export function beginInlineEdit(
  messageEl: HTMLElement,
  initialText: string,
  callbacks: InlineEditCallbacks
): void {
  const content = messageEl.querySelector<HTMLElement>('.message-content');
  if (!content || messageEl.querySelector('.message-edit-area')) return;

  const editor = document.createElement('div');
  editor.className = 'message-edit-area';

  const textarea = document.createElement('textarea');
  textarea.className = 'message-edit-textarea';
  textarea.value = initialText;
  textarea.rows = Math.min(10, Math.max(2, initialText.split('\n').length));

  const buttons = document.createElement('div');
  buttons.className = 'message-edit-buttons';

  const save = document.createElement('button');
  save.className = 'btn btn-primary btn-sm message-edit-save';
  save.textContent = 'Save & Resend';

  const cancel = document.createElement('button');
  cancel.className = 'btn btn-secondary btn-sm message-edit-cancel';
  cancel.textContent = 'Cancel';

  const hint = document.createElement('span');
  hint.className = 'message-edit-hint';
  hint.textContent = 'Replaces this message and everything after it';

  buttons.append(save, cancel, hint);
  editor.append(textarea, buttons);

  const closeEditor = (): void => {
    editor.remove();
    content.classList.remove('hidden');
  };

  cancel.addEventListener('click', closeEditor);
  save.addEventListener('click', () => {
    const text = textarea.value;
    closeEditor();
    callbacks.onSave(text);
  });
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeEditor();
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      save.click();
    }
  });

  content.classList.add('hidden');
  content.insertAdjacentElement('afterend', editor);
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);
}
