/**
 * Shared conversation header: title (inline-renameable), optional back
 * button/emoji for program variants, cost chip, action buttons.
 *
 * Rendered into the #chat-header mount in the app shell. Hidden on mobile
 * for regular conversations (the mobile header takes over); program
 * variants keep it visible via their extraClass.
 */

export interface ChatHeaderOptions {
  title: string;
  extraClass?: string;
  emoji?: string;
  onBack?: () => void;
  onRenameCommit?: (title: string) => void;
  actions?: HTMLElement[];
}

const BACK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>`;

function getHeaderEl(): HTMLElement | null {
  return document.getElementById('chat-header');
}

export function createChatHeader(opts: ChatHeaderOptions): HTMLElement {
  const header = document.createElement('div');
  header.className = 'chat-header-inner';

  if (opts.onBack) {
    const back = document.createElement('button');
    back.className = 'btn-icon chat-header-back';
    back.setAttribute('aria-label', 'Back');
    back.innerHTML = BACK_ICON;
    back.addEventListener('click', opts.onBack);
    header.appendChild(back);
  }

  if (opts.emoji) {
    const emoji = document.createElement('span');
    emoji.className = 'chat-header-emoji';
    emoji.textContent = opts.emoji;
    header.appendChild(emoji);
  }

  const title = document.createElement('h2');
  title.className = 'chat-header-title';
  title.textContent = opts.title;
  if (opts.onRenameCommit) {
    const commit = opts.onRenameCommit;
    title.classList.add('renameable');
    title.title = 'Rename conversation';
    title.addEventListener('click', () => startInlineRename(title, commit));
  }
  header.appendChild(title);

  const spacer = document.createElement('div');
  spacer.className = 'chat-header-spacer';
  header.appendChild(spacer);

  const cost = document.createElement('span');
  cost.id = 'conversation-cost';
  cost.className = 'chat-header-cost';
  header.appendChild(cost);

  for (const action of opts.actions ?? []) {
    header.appendChild(action);
  }
  return header;
}

function startInlineRename(title: HTMLElement, commit: (t: string) => void): void {
  if (title.querySelector('input')) return;
  const current = title.textContent ?? '';
  const input = document.createElement('input');
  input.className = 'chat-header-title-input';
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

export function renderChatHeader(opts: ChatHeaderOptions | null): void {
  const el = getHeaderEl();
  if (!el) return;
  el.innerHTML = '';
  el.className = 'chat-header';
  if (!opts) {
    el.classList.add('hidden');
    return;
  }
  if (opts.extraClass) el.classList.add(opts.extraClass);
  el.appendChild(createChatHeader(opts));
}

export function updateChatHeaderTitle(title: string): void {
  const el = getHeaderEl()?.querySelector('.chat-header-title');
  if (el && !el.querySelector('input')) el.textContent = title;
}
