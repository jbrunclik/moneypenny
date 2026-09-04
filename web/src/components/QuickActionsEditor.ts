/**
 * Editor modal for a program's quick actions: list (reorder via up/down,
 * edit, delete, add) + a detail form (emoji, label, body, fields).
 * Presentation + local draft state only; persistence is the caller's onSave.
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

interface EditorOptions {
  actions: QuickAction[];
  initialDraft?: Partial<QuickAction>;
  onSave: (actions: QuickAction[]) => Promise<void>;
}

let overlay: HTMLElement | null = null;
let keydownHandler: ((e: KeyboardEvent) => void) | null = null;

export function closeQuickActionsEditor(): void {
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
      <button type="button" class="qa-editor-close" title="Close">${CLOSE_ICON}</button>
    </div>
    <div class="qa-editor-body"></div>
    <div class="qa-editor-footer">
      <button type="button" class="qa-editor-cancel">Cancel</button>
      <button type="button" class="qa-editor-save">Save</button>
    </div>`;
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const body = modal.querySelector<HTMLElement>('.qa-editor-body')!;
  const footer = modal.querySelector<HTMLElement>('.qa-editor-footer')!;

  const renderList = (): void => {
    footer.classList.remove('hidden');
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
        renderList();
      } else if (target.closest('.qa-editor-move-down') && i < draftList.length - 1) {
        [draftList[i + 1], draftList[i]] = [draftList[i], draftList[i + 1]];
        renderList();
      } else if (target.closest('.qa-editor-delete')) {
        draftList.splice(i, 1);
        renderList();
      } else if (target.closest('.qa-editor-edit')) {
        renderDetail(draftList[i], i);
      }
    });
    add.addEventListener('click', () => renderDetail({}, null));
  };

  const renderDetail = (initial: Partial<QuickAction>, index: number | null): void => {
    footer.classList.add('hidden');
    clearElement(body);
    const fields = [...(initial.fields ?? [])];
    let emoji = initial.emoji ?? EMOJIS[0];
    const detail = document.createElement('div');
    detail.className = 'qa-detail';
    detail.innerHTML = `
      <div class="qa-detail-row">
        <div class="qa-detail-emoji-wrapper">
          <button type="button" class="qa-detail-emoji-trigger" title="Choose icon">${escapeHtml(emoji)}</button>
          <div class="qa-detail-emoji-popover"><div class="qa-detail-emoji-grid"></div></div>
        </div>
        <input type="text" class="qa-detail-label" placeholder="Label (shown on the chip)" maxlength="${LABEL_MAX}" value="${escapeHtml(initial.label ?? '')}" />
      </div>
      <textarea class="qa-detail-body" rows="4" maxlength="${BODY_MAX}" placeholder="What to send when you tap this chip">${escapeHtml(initial.body ?? '')}</textarea>
      <div class="qa-detail-fields">
        <div class="qa-detail-fields-title">Questions before sending <span class="qa-detail-optional">(optional)</span></div>
        <p class="qa-detail-hint">When you tap the chip, you'll be asked these first. Each answer is added to the message as a "Question: answer" line. Leave a question blank to skip it.</p>
        <div class="qa-detail-field-list"></div>
        <div class="qa-detail-field-add-row">
          <input type="text" class="qa-detail-field-input" placeholder="Add a question, e.g. RPE" maxlength="40" aria-label="New question" />
          <button type="button" class="qa-detail-field-add">Add</button>
        </div>
      </div>
      <div class="qa-detail-preview-wrap">
        <div class="qa-detail-fields-title">Message preview</div>
        <pre class="qa-detail-preview"></pre>
      </div>
      <div class="qa-detail-error" role="alert"></div>
      <div class="qa-detail-actions">
        <button type="button" class="qa-detail-back">Back</button>
        <button type="button" class="qa-detail-done">Done</button>
      </div>`;
    body.appendChild(detail);

    const grid = detail.querySelector<HTMLElement>('.qa-detail-emoji-grid')!;
    grid.innerHTML = EMOJIS.map(
      (e) => `<button type="button" class="qa-detail-emoji-option" data-emoji="${e}">${e}</button>`
    ).join('');
    const trigger = detail.querySelector<HTMLButtonElement>('.qa-detail-emoji-trigger')!;
    const popover = detail.querySelector<HTMLElement>('.qa-detail-emoji-popover')!;
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      popover.classList.toggle('open');
    });
    grid.addEventListener('click', (e) => {
      const opt = (e.target as HTMLElement).closest<HTMLElement>('.qa-detail-emoji-option');
      if (!opt?.dataset.emoji) return;
      emoji = opt.dataset.emoji;
      trigger.textContent = emoji;
      popover.classList.remove('open');
    });

    const fieldList = detail.querySelector<HTMLElement>('.qa-detail-field-list')!;
    const fieldInput = detail.querySelector<HTMLInputElement>('.qa-detail-field-input')!;
    const fieldAdd = detail.querySelector<HTMLButtonElement>('.qa-detail-field-add')!;
    const bodyInput = detail.querySelector<HTMLTextAreaElement>('.qa-detail-body')!;
    const preview = detail.querySelector<HTMLElement>('.qa-detail-preview')!;
    const renderPreview = (): void => {
      const text = bodyInput.value.trim() || '(message text)';
      const lines = fields.map((f) => `${f}: …`);
      preview.textContent = lines.length ? `${text}\n\n${lines.join('\n')}` : text;
    };
    const renderFields = (): void => {
      fieldList.innerHTML = fields
        .map(
          (f, i) => `
          <div class="qa-detail-field-row">
            <span class="qa-detail-field-name">${escapeHtml(f)}</span>
            <button type="button" class="qa-detail-field-remove" data-index="${i}" aria-label="Remove ${escapeHtml(f)}">${CLOSE_ICON}<span>Remove</span></button>
          </div>`
        )
        .join('');
      const full = fields.length >= QUICK_ACTION_FIELDS_MAX;
      fieldAdd.disabled = full;
      fieldInput.disabled = full;
      fieldInput.placeholder = full
        ? `Maximum of ${QUICK_ACTION_FIELDS_MAX} questions`
        : 'Add a question, e.g. RPE';
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
      const btn = (e.target as HTMLElement).closest<HTMLElement>('.qa-detail-field-remove');
      if (!btn) return;
      fields.splice(Number(btn.dataset.index), 1);
      renderFields();
    });

    detail.querySelector('.qa-detail-back')!.addEventListener('click', renderList);
    detail.querySelector('.qa-detail-done')!.addEventListener('click', () => {
      const label = detail.querySelector<HTMLInputElement>('.qa-detail-label')!.value.trim();
      const text = detail.querySelector<HTMLTextAreaElement>('.qa-detail-body')!.value.trim();
      const error = detail.querySelector<HTMLElement>('.qa-detail-error')!;
      if (!label || !text) {
        error.textContent = 'Label and body are required.';
        return;
      }
      const action: QuickAction = {
        id: initial.id ?? newQuickActionId(),
        emoji,
        label,
        body: text,
        fields: [...fields],
      };
      if (index === null) draftList.push(action);
      else draftList[index] = action;
      renderList();
    });
    detail.querySelector<HTMLInputElement>('.qa-detail-label')!.focus();
  };

  modal.querySelector('.qa-editor-close')!.addEventListener('click', closeQuickActionsEditor);
  modal.querySelector('.qa-editor-cancel')!.addEventListener('click', closeQuickActionsEditor);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeQuickActionsEditor();
  });
  const saveBtn = modal.querySelector<HTMLButtonElement>('.qa-editor-save')!;
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    try {
      await opts.onSave(draftList);
      closeQuickActionsEditor();
    } catch {
      toast.error('Failed to save quick actions.');
      saveBtn.disabled = false;
    }
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
