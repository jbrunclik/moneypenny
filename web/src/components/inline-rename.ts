/**
 * In-place rename of a title (the chat header's title, a project's name).
 */

/** Swap a title for an input; Enter or blur commits a changed, non-empty name, Escape restores it. */
export function startInlineRename(
  title: HTMLElement,
  commit: (t: string) => void,
  inputClass: string = 'chat-header-title-input',
): void {
  if (title.querySelector('input')) return;
  const current = title.textContent ?? '';
  const input = document.createElement('input');
  input.className = inputClass;
  input.value = current;
  title.textContent = '';
  title.appendChild(input);
  input.focus();
  input.select();
  let finished = false;
  const finish = (save: boolean): void => {
    if (finished) return;
    finished = true;
    const value = input.value.trim();
    const accepted = save && value.length > 0;
    title.textContent = accepted ? value : current;
    if (accepted && value !== current) commit(value);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish(true);
    if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}
