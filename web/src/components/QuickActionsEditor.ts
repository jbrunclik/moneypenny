/**
 * Editor modal for a program's quick actions: list (reorder via up/down,
 * edit, delete, add) + a detail form (emoji, label, body, questions).
 *
 * Autosaves: every change calls onChange with the full list and the caller
 * persists it, so closing the modal never loses work. Closing while a valid
 * detail form is open commits it first. Presentation + local draft state only.
 */
import type { QuickAction } from '../types/api';
import { escapeHtml, clearElement } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import {
  CLOSE_ICON,
  DELETE_ICON,
  EDIT_ICON,
  PLUS_ICON,
  CHEVRON_DOWN_ICON,
  SLIDERS_ICON,
} from '../utils/icons';
import { toast } from './Toast';

export const QUICK_ACTIONS_MAX = 12;
export const QUICK_ACTION_FIELDS_MAX = 6;
const LABEL_MAX = 40;
const BODY_MAX = 2000;

const EMOJIS = [
  '📋', '📊', '🏋️', '🏃', '🚴', '🧗', '🧘', '📖',
  '🧠', '✍️', '🗣️', '🔁', '📅', '✅', '⭐', '❤️',
];

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

export function showQuickActionsEditor(opts: EditorOptions): void {
  closeQuickActionsEditor();
  const draftList: QuickAction[] = opts.actions.map((a) => ({ ...a, fields: [...a.fields] }));

  overlay = document.createElement('div');
  overlay.className = 'qa-editor-overlay';
  const modal = document.createElement('div');
  modal.className = 'qa-editor';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.innerHTML = `
    <div class="qa-editor-header">
      <div class="qa-editor-title-row"><span class="qa-editor-icon">${SLIDERS_ICON}</span><h2>Quick actions</h2></div>
      <button type="button" class="qa-editor-close" title="Close" aria-label="Close">${CLOSE_ICON}</button>
    </div>
    <div class="qa-editor-body"></div>`;
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const body = modal.querySelector<HTMLElement>('.qa-editor-body')!;

  // Persist after each mutation. Keeps the local draft even on failure so a
  // retry (next change) resends everything.
  const persist = async (): Promise<void> => {
    try {
      await opts.onChange(draftList.map((a) => ({ ...a, fields: [...a.fields] })));
    } catch {
      toast.error('Failed to save quick actions.');
    }
  };

  const renderList = (): void => {
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
      const fieldsText = a.fields.length
        ? `${a.fields.length} question${a.fields.length > 1 ? 's' : ''}`
        : '';
      row.innerHTML = `
        <span class="qa-editor-row-emoji">${escapeHtml(a.emoji)}</span>
        <span class="qa-editor-row-label">${escapeHtml(a.label)}</span>
        <span class="qa-editor-row-fields">${fieldsText}</span>
        <button type="button" class="btn-icon qa-editor-move-up" title="Move up" ${i === 0 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
        <button type="button" class="btn-icon qa-editor-move-down" title="Move down" ${i === draftList.length - 1 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
        <button type="button" class="btn-icon qa-editor-edit" title="Edit">${EDIT_ICON}</button>
        <button type="button" class="btn-icon qa-editor-delete" title="Delete">${DELETE_ICON}</button>`;
      list.appendChild(row);
    });
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'qa-editor-add';
    add.innerHTML = `${PLUS_ICON}<span>Add quick action</span>`;
    add.disabled = draftList.length >= QUICK_ACTIONS_MAX;
    body.appendChild(list);
    body.appendChild(add);

    list.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      const row = target.closest<HTMLElement>('.qa-editor-row');
      if (!row) return;
      const i = Number(row.dataset.index);
      if (target.closest('.qa-editor-move-up') && i > 0) {
        [draftList[i - 1], draftList[i]] = [draftList[i], draftList[i - 1]];
      } else if (target.closest('.qa-editor-move-down') && i < draftList.length - 1) {
        [draftList[i + 1], draftList[i]] = [draftList[i], draftList[i + 1]];
      } else if (target.closest('.qa-editor-delete')) {
        draftList.splice(i, 1);
      } else if (target.closest('.qa-editor-edit')) {
        renderDetail(draftList[i], i);
        return;
      } else {
        return;
      }
      renderList();
      void persist();
    });
    add.addEventListener('click', () => renderDetail({}, null));
  };

  const renderDetail = (initial: Partial<QuickAction>, index: number | null): void => {
    clearElement(body);
    const fields = [...(initial.fields ?? [])];
    let emoji = initial.emoji ?? EMOJIS[0];
    const detail = document.createElement('div');
    detail.className = 'qa-detail';
    detail.innerHTML = `
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
    body.appendChild(detail);

    const grid = detail.querySelector<HTMLElement>('.qa-detail-emoji-grid')!;
    grid.innerHTML = EMOJIS.map(
      (e) => `<button type="button" class="qa-detail-emoji-option" data-emoji="${e}">${e}</button>`
    ).join('');
    const emojiInput = detail.querySelector<HTMLInputElement>('.qa-detail-emoji-input')!;
    const popover = detail.querySelector<HTMLElement>('.qa-detail-emoji-popover')!;
    // Any emoji goes: the input takes the OS emoji keyboard; the grid is
    // just one-tap suggestions. Keep the first grapheme so a single emoji
    // (with skin tone / ZWJ sequences) survives but "abc" collapses to "a".
    const applyEmojiInput = (): void => {
      const first = firstGrapheme(emojiInput.value.trim());
      if (first) emoji = first;
    };
    emojiInput.addEventListener('focus', () => popover.classList.add('open'));
    emojiInput.addEventListener('click', (e) => {
      e.stopPropagation();
      popover.classList.add('open');
    });
    emojiInput.addEventListener('input', applyEmojiInput);
    emojiInput.addEventListener('blur', () => {
      applyEmojiInput();
      emojiInput.value = emoji;
    });
    grid.addEventListener('click', (e) => {
      const opt = (e.target as HTMLElement).closest<HTMLElement>('.qa-detail-emoji-option');
      if (!opt?.dataset.emoji) return;
      emoji = opt.dataset.emoji;
      emojiInput.value = emoji;
      popover.classList.remove('open');
    });
    detail.addEventListener('click', (e) => {
      const wrapper = detail.querySelector('.qa-detail-emoji-wrapper');
      if (wrapper && !wrapper.contains(e.target as Node)) popover.classList.remove('open');
    });

    const fieldList = detail.querySelector<HTMLElement>('.qa-detail-field-list')!;
    const fieldInput = detail.querySelector<HTMLInputElement>('.qa-detail-field-input')!;
    const fieldAdd = detail.querySelector<HTMLButtonElement>('.qa-detail-field-add')!;
    const labelInput = detail.querySelector<HTMLInputElement>('.qa-detail-label')!;
    const bodyInput = detail.querySelector<HTMLTextAreaElement>('.qa-detail-body')!;
    const preview = detail.querySelector<HTMLElement>('.qa-detail-preview')!;
    const renderPreview = (): void => {
      const text = bodyInput.value.trim() || '…';
      const lines = fields.map((f) => `${f}: …`);
      preview.textContent = lines.length ? `${text}\n\n${lines.join('\n')}` : text;
    };
    const renderFields = (): void => {
      fieldList.innerHTML = fields
        .map(
          (f, i) => `
          <div class="qa-detail-field-row" data-index="${i}">
            <span class="qa-detail-field-name">${escapeHtml(f)}</span>
            <span class="qa-detail-field-controls">
              <button type="button" class="btn-icon qa-detail-field-up" title="Move up" aria-label="Move ${escapeHtml(f)} up" ${i === 0 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
              <button type="button" class="btn-icon qa-detail-field-down" title="Move down" aria-label="Move ${escapeHtml(f)} down" ${i === fields.length - 1 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
              <button type="button" class="qa-detail-field-remove" aria-label="Remove ${escapeHtml(f)}" title="Remove">${CLOSE_ICON}</button>
            </span>
          </div>`
        )
        .join('');
      const full = fields.length >= QUICK_ACTION_FIELDS_MAX;
      fieldAdd.disabled = full;
      fieldInput.disabled = full;
      fieldInput.placeholder = full ? `Max ${QUICK_ACTION_FIELDS_MAX}` : 'New question';
      renderPreview();
    };
    renderFields();
    bodyInput.addEventListener('input', renderPreview);
    const addField = (): void => {
      const v = fieldInput.value.trim();
      if (!v || fields.length >= QUICK_ACTION_FIELDS_MAX) return;
      fields.push(v);
      fieldInput.value = '';
      renderFields();
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
        [fields[i - 1], fields[i]] = [fields[i], fields[i - 1]];
      } else if (target.closest('.qa-detail-field-down') && i < fields.length - 1) {
        [fields[i + 1], fields[i]] = [fields[i], fields[i + 1]];
      } else if (target.closest('.qa-detail-field-remove')) {
        fields.splice(i, 1);
      } else {
        return;
      }
      renderFields();
    });

    /** Validate + write the form into the draft list and persist. */
    const commit = (): boolean => {
      const label = labelInput.value.trim();
      const text = bodyInput.value.trim();
      if (!label || !text) return false;
      // Stray question typed but not added: keep it rather than lose it
      const pending = fieldInput.value.trim();
      if (pending && fields.length < QUICK_ACTION_FIELDS_MAX) fields.push(pending);
      applyEmojiInput();
      const action: QuickAction = {
        id: initial.id ?? newQuickActionId(),
        emoji: emoji || EMOJIS[0],
        label,
        body: text,
        fields: [...fields],
      };
      if (index === null) draftList.push(action);
      else draftList[index] = action;
      void persist();
      return true;
    };
    commitOpenDetail = commit;

    detail.querySelector('.qa-detail-back')!.addEventListener('click', renderList);
    detail.querySelector('.qa-detail-done')!.addEventListener('click', () => {
      if (!commit()) {
        detail.querySelector<HTMLElement>('.qa-detail-error')!.textContent =
          'Label and body are required.';
        return;
      }
      renderList();
    });
    labelInput.focus();
  };

  modal.querySelector('.qa-editor-close')!.addEventListener('click', closeQuickActionsEditor);
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

  if (opts.initialDraft) renderDetail(opts.initialDraft, null);
  else renderList();
}
