/**
 * A setup change as people read it: one row per changed field (the old value
 * struck through, the new one), and "Based on" - each line the day and the
 * user's words, or the item it quotes. Shared by the Reviews' cards
 * (QuickActionsReview.ts) and the chat's setup change cards (proposal-card.ts).
 */
import type { SetupSuggestion } from '../types/api';
import { createElement } from '../utils/dom';

/** One changed field: its name, the old value struck through (if any), the new one. */
function fieldRow(change: SetupSuggestion['changes'][number]): HTMLElement {
  const values: HTMLElement[] = [];
  if (change.before) values.push(createElement('del', { class: 'qa-review-old' }, [change.before]));
  values.push(
    change.after
      ? createElement('ins', { class: 'qa-review-new' }, [change.after])
      : createElement('span', { class: 'qa-review-removed' }, ['Removed'])
  );
  return createElement('div', { class: 'qa-review-field' }, [
    createElement('div', { class: 'qa-review-field-name' }, [change.field]),
    ...values,
  ]);
}

const EVIDENCE_LINE = /^(\d{4})-(\d{2})-(\d{2}):\s*(.*)$/s;
const QUOTE_MARKS = /^["'“”‘’]+|["'“”‘’]+$/g;

/** "2026-11-09: 'plan my week'" -> the day (readable, machine date kept) + the words as a quote */
const ITEM_LINE = /^(Memory|Instructions):\s*(.*)$/s;

/** "Memory: ..." / "Instructions: ..." -> what it quotes, labelled (clean-up evidence) */
function itemRow(kind: string, quoted: string): HTMLElement {
  return createElement('li', {}, [
    createElement('span', { class: 'qa-review-evidence-kind' }, [kind]),
    createElement('q', {}, [quoted.trim().replace(QUOTE_MARKS, '')]),
  ]);
}

function evidenceRow(line: string): HTMLElement {
  const item = ITEM_LINE.exec(line);
  if (item) return itemRow(item[1] ?? '', item[2] ?? '');
  const match = EVIDENCE_LINE.exec(line);
  if (!match) return createElement('li', {}, [createElement('q', {}, [line.replace(QUOTE_MARKS, '')])]);
  const [, y, m, d, said = ''] = match;
  const day = new Date(Number(y), Number(m) - 1, Number(d));
  const label = day.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return createElement('li', {}, [
    createElement('time', { datetime: `${y}-${m}-${d}` }, [label]),
    createElement('q', {}, [said.trim().replace(QUOTE_MARKS, '')]),
  ]);
}

/** What a setup change changes, one row per field. */
export function changeRows(changes: SetupSuggestion['changes']): HTMLElement {
  return createElement('div', { class: 'qa-review-change' }, changes.map(fieldRow));
}

/** "Based on": each line as the day and the user's words, or the item it quotes. */
export function evidenceList(lines: string[]): HTMLElement {
  return createElement('div', { class: 'qa-review-evidence' }, [
    createElement('div', { class: 'qa-review-evidence-title' }, ['Based on']),
    createElement('ul', {}, lines.map(evidenceRow)),
  ]);
}
