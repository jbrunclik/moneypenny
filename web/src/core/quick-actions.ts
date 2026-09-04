/**
 * Quick actions: one-tap saved prompts for program conversations.
 *
 * Owns: message composition, the chip row inside the composer pill (mounted
 * only while a program conversation is open), "composer mode" (a tapped
 * action's questions rendered inside the pill, the textarea becoming the
 * note), the "/" slash menu, sending, and the editor glue. Components in
 * components/QuickAction*.ts are presentation only.
 */
import type { QuickAction } from '../types/api';
import { useStore } from '../state/store';
import { renderQuickActionsBar, setQuickActionsBarDisabled } from '../components/QuickActionsBar';
import {
  focusQuickActionField,
  readQuickActionComposerValues,
  renderQuickActionComposer,
} from '../components/QuickActionComposer';
import {
  clearSlashMenu,
  filterQuickActions,
  renderSlashMenu,
} from '../components/QuickActionsSlashMenu';
import { showQuickActionsEditor } from '../components/QuickActionsEditor';
import { isMobileViewport, setComposerHasExternalContent } from '../components/MessageInput';
import { toast } from '../components/Toast';
import { getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { registerComposerHook, sendMessage } from './messaging';

const log = createLogger('quick-actions');

const NOTE_PLACEHOLDER = 'Add a note…';

/**
 * Body, blank line, one `Label: value` line per non-empty field (in field
 * order), then the free-text note as its own paragraph. Multi-line values
 * indent continuation lines by two spaces. Nothing to add -> body only.
 */
export function composeQuickActionMessage(
  action: QuickAction,
  values: Record<string, string>,
  note = ''
): string {
  const parts = [action.body.trim()];
  const lines: string[] = [];
  for (const field of action.fields) {
    const value = (values[field] ?? '').trim();
    if (!value) continue;
    lines.push(`${field}: ${value.split('\n').join('\n  ')}`);
  }
  if (lines.length) parts.push(lines.join('\n'));
  const trimmedNote = note.trim();
  if (trimmedNote) parts.push(trimmedNote);
  return parts.join('\n\n');
}

export interface QuickActionsContext {
  namespace: 'sports' | 'language';
  programId: string;
  actions: QuickAction[];
  /** Persist the full list; resolves with the server's copy. */
  save: (actions: QuickAction[]) => Promise<QuickAction[]>;
}

let current: QuickActionsContext | null = null;
let unsubscribeStore: (() => void) | null = null;
let mode: { action: QuickAction } | null = null;
let slash: { items: QuickAction[]; index: number } | null = null;
let defaultPlaceholder = '';

// ---------------------------------------------------------------------------
// Visibility
// ---------------------------------------------------------------------------

export function shouldShowQuickActionsBar(input: {
  mobile: boolean;
  composerEmpty: boolean;
  streaming: boolean;
}): boolean {
  if (!input.mobile) return true;
  return input.composerEmpty && !input.streaming;
}

function isCurrentConversationStreaming(): boolean {
  const state = useStore.getState();
  const convId = state.currentConversation?.id;
  return convId !== undefined && state.activeRequests.has(convId);
}

/** Re-evaluate the chip row's visibility + disabled state. */
export function refreshQuickActionsBar(): void {
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (!bar) return;
  if (!current || mode || slash) {
    bar.classList.add('hidden');
    return;
  }
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  const streaming = isCurrentConversationStreaming();
  const visible = shouldShowQuickActionsBar({
    mobile: isMobileViewport(),
    composerEmpty: !textarea || textarea.value.trim() === '',
    streaming,
  });
  bar.classList.toggle('hidden', !visible);
  setQuickActionsBarDisabled(bar, streaming);
}

function renderCurrent(): void {
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (!bar || !current) return;
  renderQuickActionsBar(
    bar,
    current.actions,
    (action) => activateQuickAction(action),
    () => openQuickActionsEditor()
  );
  refreshQuickActionsBar();
}

// ---------------------------------------------------------------------------
// Activation: send now, or enter composer mode
// ---------------------------------------------------------------------------

function activateQuickAction(action: QuickAction): void {
  if (isCurrentConversationStreaming()) {
    toast.info('Please wait for the current response to finish.');
    return;
  }
  closeSlashMenu();
  if (action.fields.length === 0) {
    void sendQuickAction(action, {});
    return;
  }
  enterComposerMode(action);
}

/** Compose the message, put it in the composer and send through the normal path. */
export async function sendQuickAction(
  action: QuickAction,
  values: Record<string, string>
): Promise<void> {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (!textarea) return;
  const text = composeQuickActionMessage(action, values);
  log.info('Sending quick action', { id: action.id, fields: Object.keys(values).length });
  textarea.value = text;
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sendMessage();
}

export function isComposerModeActive(): boolean {
  return mode !== null;
}

function enterComposerMode(action: QuickAction): void {
  const modeEl = getElementById<HTMLElement>('quick-action-mode');
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (!modeEl || !textarea) return;
  mode = { action };
  renderQuickActionComposer(modeEl, {
    action,
    onCancel: exitComposerMode,
    onEscape: exitComposerMode,
    onFieldEnter: (index, isLast) => {
      if (!isLast) {
        focusQuickActionField(modeEl, index + 1);
        return;
      }
      if (isMobileViewport()) textarea.focus();
      else void sendMessage();
    },
  });
  modeEl.classList.remove('hidden');
  textarea.placeholder = NOTE_PLACEHOLDER;
  setComposerHasExternalContent(true);
  refreshQuickActionsBar();
  focusQuickActionField(modeEl, 0);
  log.debug('Composer mode entered', { id: action.id });
}

export function exitComposerMode(): void {
  if (!mode) return;
  mode = null;
  const modeEl = getElementById<HTMLElement>('quick-action-mode');
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (modeEl) {
    modeEl.classList.add('hidden');
    modeEl.innerHTML = '';
  }
  if (textarea) textarea.placeholder = defaultPlaceholder;
  setComposerHasExternalContent(false);
  refreshQuickActionsBar();
}

/** messaging.sendMessage() asks for the outgoing text through this hook. */
function transformOutgoingText(text: string): string {
  if (!mode) return text;
  const modeEl = getElementById<HTMLElement>('quick-action-mode');
  const values = modeEl ? readQuickActionComposerValues(modeEl) : {};
  return composeQuickActionMessage(mode.action, values, text);
}

// ---------------------------------------------------------------------------
// Slash menu
// ---------------------------------------------------------------------------

function slashFilterFromComposer(): string | null {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (!textarea || !current || mode) return null;
  const v = textarea.value;
  if (!v.startsWith('/') || v.includes('\n')) return null;
  return v.slice(1);
}

function syncSlashMenu(): void {
  const container = getElementById<HTMLElement>('quick-action-slash');
  if (!container) return;
  const filter = slashFilterFromComposer();
  if (filter === null || !current) {
    closeSlashMenu();
    return;
  }
  const items = filterQuickActions(current.actions, filter);
  if (items.length === 0) {
    closeSlashMenu();
    return;
  }
  const index = slash ? Math.min(slash.index, items.length - 1) : 0;
  slash = { items, index };
  renderSlashMenu(container, items, index, pickFromSlashMenu);
  refreshQuickActionsBar();
}

function closeSlashMenu(): void {
  const wasOpen = slash !== null;
  slash = null;
  const container = getElementById<HTMLElement>('quick-action-slash');
  if (container) clearSlashMenu(container);
  if (wasOpen) refreshQuickActionsBar();
}

function pickFromSlashMenu(action: QuickAction): void {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (textarea) {
    textarea.value = '';
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  }
  closeSlashMenu();
  activateQuickAction(action);
}

/** Capture-phase keydown on the textarea: runs before MessageInput's Enter-to-send. */
function handleComposerKeydown(e: KeyboardEvent): void {
  if (mode && e.key === 'Escape') {
    e.preventDefault();
    e.stopImmediatePropagation();
    exitComposerMode();
    return;
  }
  if (!slash) return;
  const container = getElementById<HTMLElement>('quick-action-slash');
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const delta = e.key === 'ArrowDown' ? 1 : -1;
    slash.index = (slash.index + delta + slash.items.length) % slash.items.length;
    if (container) renderSlashMenu(container, slash.items, slash.index, pickFromSlashMenu);
    return;
  }
  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault();
    e.stopImmediatePropagation();
    pickFromSlashMenu(slash.items[slash.index]);
    return;
  }
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopImmediatePropagation();
    closeSlashMenu();
  }
}

// ---------------------------------------------------------------------------
// Mount / unmount / init
// ---------------------------------------------------------------------------

export function getQuickActionsContext(): QuickActionsContext | null {
  return current;
}

/** Open the per-program editor; autosaves through the context and re-renders the chips. */
export function openQuickActionsEditor(draft?: Partial<QuickAction>): void {
  const ctx = current;
  if (!ctx) return;
  showQuickActionsEditor({
    actions: ctx.actions,
    initialDraft: draft,
    onChange: async (actions) => {
      const saved = await ctx.save(actions);
      if (current && current.programId === ctx.programId) {
        current.actions = saved;
        renderCurrent();
      }
    },
  });
}

export function mountQuickActionsBar(ctx: QuickActionsContext): void {
  current = ctx;
  document.body.classList.add('has-quick-actions');
  renderCurrent();
}

export function unmountQuickActionsBar(): void {
  exitComposerMode();
  closeSlashMenu();
  current = null;
  document.body.classList.remove('has-quick-actions');
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (bar) bar.classList.add('hidden');
}

/** Wire composer + store listeners once at app init. */
export function initQuickActions(): void {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  defaultPlaceholder = textarea?.placeholder ?? '';
  textarea?.addEventListener('input', () => {
    refreshQuickActionsBar();
    syncSlashMenu();
  });
  textarea?.addEventListener('keydown', handleComposerKeydown, { capture: true });
  window.addEventListener('resize', refreshQuickActionsBar);
  registerComposerHook({
    transform: transformOutgoingText,
    onConsumed: () => exitComposerMode(),
  });
  unsubscribeStore?.();
  unsubscribeStore = useStore.subscribe(
    (state) => state.activeRequests,
    () => refreshQuickActionsBar()
  );
  document.addEventListener('message:save-quick-action', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    const convId = useStore.getState().currentConversation?.id;
    if (!convId || !current) return;
    const message = useStore
      .getState()
      .getMessages(convId)
      .find((m) => m.id === messageId);
    if (!message) return;
    openQuickActionsEditor({ body: message.content });
  });
}
