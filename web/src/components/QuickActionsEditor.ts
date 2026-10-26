/**
 * Editor modal for a program's quick actions: list (reorder via up/down,
 * edit, delete, add) + a detail form (emoji, label, body, questions).
 *
 * Autosaves: every change calls onChange with the full list and the caller
 * persists it, so closing the modal never loses work. Closing while a valid
 * detail form is open commits it first. Presentation + local draft state only.
 */
import type { QuickAction } from '../types/api';
import { escapeHtml, clearElement, createElement } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import {
  CLOSE_ICON,
  DELETE_ICON,
  EDIT_ICON,
  PLUS_ICON,
  CHEVRON_DOWN_ICON,
  SLIDERS_ICON,
  createIconElement,
  setIcon,
} from '../utils/icons';
import { toast } from './Toast';

export const QUICK_ACTIONS_MAX = 12;
export const QUICK_ACTION_FIELDS_MAX = 6;
const LABEL_MAX = 40;
const BODY_MAX = 2000;

const DEFAULT_EMOJI = '📋';
const EMOJIS = [
  DEFAULT_EMOJI, '📊', '🏋️', '🏃', '🚴', '🧗', '🧘', '📖',
  '🧠', '✍️', '🗣️', '🔁', '📅', '✅', '⭐', '❤️',
];

/** Swap two entries in place; a no-op when either index is out of range. */
function swapItems<T>(items: T[], i: number, j: number): void {
  const a = items[i];
  const b = items[j];
  if (a === undefined || b === undefined) return;
  items[i] = b;
  items[j] = a;
}

export function newQuickActionId(): string {
  return Math.random().toString(36).slice(2, 10);
}

/** First user-perceived character (grapheme cluster) of a string, or ''. */
export function firstGrapheme(value: string): string {
  if (!value) return '';
  const Segmenter = (
    Intl as unknown as {
      Segmenter?: new () => { segment(s: string): Iterable<{ segment: string }> };
    }
  ).Segmenter;
  if (Segmenter) {
    for (const part of new Segmenter().segment(value)) return part.segment;
    return '';
  }
  return Array.from(value)[0] ?? '';
}

interface EditorOptions {
  actions: QuickAction[];
  initialDraft?: Partial<QuickAction>;
  /** Called after every change with the full ordered list; persist it. */
  onChange: (actions: QuickAction[]) => Promise<void>;
}

interface DetailParts {
  grid: HTMLElement;
  emojiInput: HTMLInputElement;
  popover: HTMLElement;
  fieldList: HTMLElement;
  fieldInput: HTMLInputElement;
  fieldAdd: HTMLButtonElement;
  labelInput: HTMLInputElement;
  bodyInput: HTMLTextAreaElement;
  preview: HTMLElement;
}

/** The detail form's controls, or null if its markup is missing any of them. */
function queryDetailParts(detail: HTMLElement): DetailParts | null {
  const grid = detail.querySelector<HTMLElement>('.qa-detail-emoji-grid');
  const emojiInput = detail.querySelector<HTMLInputElement>('.qa-detail-emoji-input');
  const popover = detail.querySelector<HTMLElement>('.qa-detail-emoji-popover');
  const fieldList = detail.querySelector<HTMLElement>('.qa-detail-field-list');
  const fieldInput = detail.querySelector<HTMLInputElement>('.qa-detail-field-input');
  const fieldAdd = detail.querySelector<HTMLButtonElement>('.qa-detail-field-add');
  const labelInput = detail.querySelector<HTMLInputElement>('.qa-detail-label');
  const bodyInput = detail.querySelector<HTMLTextAreaElement>('.qa-detail-body');
  const preview = detail.querySelector<HTMLElement>('.qa-detail-preview');
  if (!grid || !emojiInput || !popover || !fieldList || !fieldInput || !fieldAdd || !labelInput || !bodyInput || !preview) {
    return null;
  }
  return { grid, emojiInput, popover, fieldList, fieldInput, fieldAdd, labelInput, bodyInput, preview };
}

let overlay: HTMLElement | null = null;
let keydownHandler: ((e: KeyboardEvent) => void) | null = null;
/** Set while a detail form is open: commits it if valid (true) or reports invalid (false). */
let commitOpenDetail: (() => boolean) | null = null;

export function closeQuickActionsEditor(): void {
  // Closing over a half-edited action must not lose it: commit when valid.
  if (commitOpenDetail) {
    const commit = commitOpenDetail;
    commitOpenDetail = null;
    commit();
  }
  if (keydownHandler) document.removeEventListener('keydown', keydownHandler);
  keydownHandler = null;
  overlay?.remove();
  overlay = null;
}

/** One open editor: its body element, the draft list, and how to persist it. */
interface EditorSession {
  body: HTMLElement;
  draftList: QuickAction[];
  /** Persist after each mutation; keeps the draft on failure so the next change resends everything. */
  persist: () => Promise<void>;
}

/** The detail form's working state: the chosen icon and the questions. */
interface DetailDraft {
  emoji: string;
  fields: string[];
}

function listRowHtml(a: QuickAction, i: number, count: number): string {
  const fieldsText = a.fields.length
    ? `${a.fields.length} question${a.fields.length > 1 ? 's' : ''}`
    : '';
  return `
        <span class="qa-editor-row-emoji">${escapeHtml(a.emoji)}</span>
        <span class="qa-editor-row-label">${escapeHtml(a.label)}</span>
        <span class="qa-editor-row-fields">${fieldsText}</span>
        <button type="button" class="btn-icon qa-editor-move-up" title="Move up" ${i === 0 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
        <button type="button" class="btn-icon qa-editor-move-down" title="Move down" ${i === count - 1 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
        <button type="button" class="btn-icon qa-editor-edit" title="Edit">${EDIT_ICON}</button>
        <button type="button" class="btn-icon qa-editor-delete" title="Delete">${DELETE_ICON}</button>`;
}

/** A list row's move/delete/edit click; re-renders and persists after a change. */
function handleListClick(session: EditorSession, e: MouseEvent): void {
  const { draftList } = session;
  const target = e.target as HTMLElement;
  const row = target.closest<HTMLElement>('.qa-editor-row');
  if (!row) return;
  const i = Number(row.dataset.index);
  if (target.closest('.qa-editor-move-up') && i > 0) {
    swapItems(draftList, i - 1, i);
  } else if (target.closest('.qa-editor-move-down') && i < draftList.length - 1) {
    swapItems(draftList, i + 1, i);
  } else if (target.closest('.qa-editor-delete')) {
    draftList.splice(i, 1);
  } else if (target.closest('.qa-editor-edit')) {
    const action = draftList[i];
    if (action) renderDetail(session, action, i);
    return;
  } else {
    return;
  }
  renderList(session);
  void session.persist();
}

function renderList(session: EditorSession): void {
  const { body, draftList } = session;
  commitOpenDetail = null;
  clearElement(body);
  const list = document.createElement('div');
  list.className = 'qa-editor-list';
  if (draftList.length === 0) {
    list.innerHTML = `<p class="qa-editor-empty">No quick actions yet.</p>`;
  }
  draftList.forEach((a, i) => {
    const row = document.createElement('div');
    row.className = 'qa-editor-row';
    row.dataset.index = String(i);
    row.innerHTML = listRowHtml(a, i, draftList.length);
    list.appendChild(row);
  });
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'qa-editor-add';
  setIcon(add, PLUS_ICON);
  add.append(createElement('span', {}, ['Add quick action']));
  add.disabled = draftList.length >= QUICK_ACTIONS_MAX;
  body.appendChild(list);
  body.appendChild(add);

  list.addEventListener('click', (e) => handleListClick(session, e));
  add.addEventListener('click', () => renderDetail(session, {}, null));
}

function detailFormHtml(initial: Partial<QuickAction>, emoji: string): string {
  return `
      <div class="qa-detail-row">
        <div class="qa-detail-emoji-wrapper">
          <input type="text" class="qa-detail-emoji-input" value="${escapeHtml(emoji)}" maxlength="16" autocomplete="off" aria-label="Icon - type any emoji or pick a suggestion" title="Type any emoji" />
          <div class="qa-detail-emoji-popover"><div class="qa-detail-emoji-grid"></div></div>
        </div>
        <input type="text" class="qa-detail-label" placeholder="Label" maxlength="${LABEL_MAX}" value="${escapeHtml(initial.label ?? '')}" aria-label="Label" />
      </div>
      <textarea class="qa-detail-body" rows="3" maxlength="${BODY_MAX}" placeholder="Message" aria-label="Message">${escapeHtml(initial.body ?? '')}</textarea>
      <div class="qa-detail-fields">
        <div class="qa-detail-section-title">Questions</div>
        <div class="qa-detail-field-list"></div>
        <div class="qa-detail-field-add-row">
          <input type="text" class="qa-detail-field-input" placeholder="New question" maxlength="40" aria-label="New question" />
          <button type="button" class="qa-detail-field-add">Add</button>
        </div>
      </div>
      <div class="qa-detail-preview-wrap">
        <div class="qa-detail-section-title">Preview</div>
        <pre class="qa-detail-preview"></pre>
      </div>
      <div class="qa-detail-error" role="alert"></div>
      <div class="qa-detail-actions">
        <button type="button" class="qa-detail-back">Cancel</button>
        <button type="button" class="qa-detail-done">Done</button>
      </div>`;
}

/**
 * Any emoji goes: the input takes the OS emoji keyboard; the grid is just
 * one-tap suggestions. Keep the first grapheme so a single emoji (with skin
 * tone / ZWJ sequences) survives but "abc" collapses to "a".
 */
function applyEmojiInput(parts: DetailParts, draft: DetailDraft): void {
  const first = firstGrapheme(parts.emojiInput.value.trim());
  if (first) draft.emoji = first;
}

function wireEmojiPicker(detail: HTMLElement, parts: DetailParts, draft: DetailDraft): void {
  const { grid, emojiInput, popover } = parts;
  grid.replaceChildren(
    ...EMOJIS.map((e) => createElement('button', { type: 'button', class: 'qa-detail-emoji-option', 'data-emoji': e }, [e]))
  );
  emojiInput.addEventListener('focus', () => popover.classList.add('open'));
  emojiInput.addEventListener('click', (e) => {
    e.stopPropagation();
    popover.classList.add('open');
  });
  emojiInput.addEventListener('input', () => applyEmojiInput(parts, draft));
  emojiInput.addEventListener('blur', () => {
    applyEmojiInput(parts, draft);
    emojiInput.value = draft.emoji;
  });
  grid.addEventListener('click', (e) => {
    const opt = (e.target as HTMLElement).closest<HTMLElement>('.qa-detail-emoji-option');
    if (!opt?.dataset.emoji) return;
    draft.emoji = opt.dataset.emoji;
    emojiInput.value = draft.emoji;
    popover.classList.remove('open');
  });
  detail.addEventListener('click', (e) => {
    const wrapper = detail.querySelector('.qa-detail-emoji-wrapper');
    if (wrapper && !wrapper.contains(e.target as Node)) popover.classList.remove('open');
  });
}

function fieldRowHtml(f: string, i: number, count: number): string {
  return `
          <div class="qa-detail-field-row" data-index="${i}">
            <span class="qa-detail-field-name">${escapeHtml(f)}</span>
            <span class="qa-detail-field-controls">
              <button type="button" class="btn-icon qa-detail-field-up" title="Move up" aria-label="Move ${escapeHtml(f)} up" ${i === 0 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
              <button type="button" class="btn-icon qa-detail-field-down" title="Move down" aria-label="Move ${escapeHtml(f)} down" ${i === count - 1 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
              <button type="button" class="qa-detail-field-remove" aria-label="Remove ${escapeHtml(f)}" title="Remove">${CLOSE_ICON}</button>
            </span>
          </div>`;
}

/** The message as it will be sent: the body, then a line per question. */
function renderPreview(parts: DetailParts, fields: string[]): void {
  const text = parts.bodyInput.value.trim() || '…';
  const lines = fields.map((f) => `${f}: …`);
  parts.preview.textContent = lines.length ? `${text}\n\n${lines.join('\n')}` : text;
}

function renderFields(parts: DetailParts, fields: string[]): void {
  const { fieldList, fieldInput, fieldAdd } = parts;
  fieldList.innerHTML = fields.map((f, i) => fieldRowHtml(f, i, fields.length)).join('');
  const full = fields.length >= QUICK_ACTION_FIELDS_MAX;
  fieldAdd.disabled = full;
  fieldInput.disabled = full;
  fieldInput.placeholder = full ? `Max ${QUICK_ACTION_FIELDS_MAX}` : 'New question';
  renderPreview(parts, fields);
}

/** The questions editor: add (button or Enter), reorder, remove; the preview follows. */
function wireFieldEditor(parts: DetailParts, fields: string[]): void {
  const { fieldList, fieldInput, fieldAdd, bodyInput } = parts;
  renderFields(parts, fields);
  bodyInput.addEventListener('input', () => renderPreview(parts, fields));
  const addField = (): void => {
    const v = fieldInput.value.trim();
    if (!v || fields.length >= QUICK_ACTION_FIELDS_MAX) return;
    fields.push(v);
    fieldInput.value = '';
    renderFields(parts, fields);
    fieldInput.focus();
  };
  fieldAdd.addEventListener('click', addField);
  fieldInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addField();
    }
  });
  fieldList.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    const row = target.closest<HTMLElement>('.qa-detail-field-row');
    if (!row) return;
    const i = Number(row.dataset.index);
    if (target.closest('.qa-detail-field-up') && i > 0) {
      swapItems(fields, i - 1, i);
    } else if (target.closest('.qa-detail-field-down') && i < fields.length - 1) {
      swapItems(fields, i + 1, i);
    } else if (target.closest('.qa-detail-field-remove')) {
      fields.splice(i, 1);
    } else {
      return;
    }
    renderFields(parts, fields);
  });
}

/** Validate + write the form into the draft list and persist; false when label or body is missing. */
function commitDetail(
  session: EditorSession,
  parts: DetailParts,
  draft: DetailDraft,
  initial: Partial<QuickAction>,
  index: number | null
): boolean {
  const label = parts.labelInput.value.trim();
  const text = parts.bodyInput.value.trim();
  if (!label || !text) return false;
  // Stray question typed but not added: keep it rather than lose it
  const pending = parts.fieldInput.value.trim();
  if (pending && draft.fields.length < QUICK_ACTION_FIELDS_MAX) draft.fields.push(pending);
  applyEmojiInput(parts, draft);
  const action: QuickAction = {
    id: initial.id ?? newQuickActionId(),
    emoji: draft.emoji || DEFAULT_EMOJI,
    label,
    body: text,
    fields: [...draft.fields],
  };
  if (index === null) session.draftList.push(action);
  else session.draftList[index] = action;
  void session.persist();
  return true;
}

function renderDetail(session: EditorSession, initial: Partial<QuickAction>, index: number | null): void {
  const { body } = session;
  clearElement(body);
  const draft: DetailDraft = { emoji: initial.emoji ?? DEFAULT_EMOJI, fields: [...(initial.fields ?? [])] };
  const detail = document.createElement('div');
  detail.className = 'qa-detail';
  detail.innerHTML = detailFormHtml(initial, draft.emoji);
  body.appendChild(detail);

  const parts = queryDetailParts(detail);
  if (!parts) return;
  wireEmojiPicker(detail, parts, draft);
  wireFieldEditor(parts, draft.fields);

  const commit = (): boolean => commitDetail(session, parts, draft, initial, index);
  commitOpenDetail = commit;

  detail.querySelector('.qa-detail-back')?.addEventListener('click', () => renderList(session));
  detail.querySelector('.qa-detail-done')?.addEventListener('click', () => {
    if (!commit()) {
      const errorEl = detail.querySelector<HTMLElement>('.qa-detail-error');
      if (errorEl) errorEl.textContent = 'Label and body are required.';
      return;
    }
    renderList(session);
  });
  parts.labelInput.focus();
}

export function showQuickActionsEditor(opts: EditorOptions): void {
  closeQuickActionsEditor();
  const draftList: QuickAction[] = opts.actions.map((a) => ({ ...a, fields: [...a.fields] }));

  overlay = document.createElement('div');
  overlay.className = 'qa-editor-overlay';
  const modal = document.createElement('div');
  modal.className = 'qa-editor';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  const closeBtn = createElement('button', {
    type: 'button',
    class: 'qa-editor-close dialog-close',
    title: 'Close',
    'aria-label': 'Close',
  });
  setIcon(closeBtn, CLOSE_ICON);
  modal.append(
    createElement('div', { class: 'qa-editor-header' }, [
      createElement('div', { class: 'qa-editor-title-row' }, [
        createIconElement('qa-editor-icon', SLIDERS_ICON),
        createElement('h2', { class: 'dialog-title' }, ['Quick actions']),
      ]),
      closeBtn,
    ]),
    createElement('div', { class: 'qa-editor-body' })
  );
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const body = modal.querySelector<HTMLElement>('.qa-editor-body');
  if (!body) {
    closeQuickActionsEditor();
    return;
  }

  const session: EditorSession = {
    body,
    draftList,
    persist: async (): Promise<void> => {
      try {
        await opts.onChange(draftList.map((a) => ({ ...a, fields: [...a.fields] })));
      } catch {
        toast.error('Failed to save quick actions.');
      }
    },
  };

  modal.querySelector('.qa-editor-close')?.addEventListener('click', closeQuickActionsEditor);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeQuickActionsEditor();
  });
  keydownHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      closeQuickActionsEditor();
      return;
    }
    trapTabKey(modal, e);
  };
  document.addEventListener('keydown', keydownHandler);

  if (opts.initialDraft) renderDetail(session, opts.initialDraft, null);
  else renderList(session);
}
