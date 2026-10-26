/**
 * Every claim of one answer, problems first. Bottom sheet on mobile, popover
 * on desktop; a row scrolls to the claim in the answer and flashes it.
 */
import { CLAIM_FLASH_MS, MOBILE_BREAKPOINT_PX } from '../config';
import { useStore } from '../state/store';
import type { ClaimAnnotation, ClaimVerdict, Message, Source } from '../types/api';
import { createElement, prefersReducedMotion } from '../utils/dom';
import { attachSheetDismiss } from '../utils/sheet-gesture';
import { closeClaimCard, plainQuote } from './ClaimCard';
import { displayHost, getMessageAnnotations, getMessageGrounding } from './messages/annotations';
import { groundingStrings } from './messages/grounding-strings';
import { trapTabKey } from '../utils/focus-trap';

const SHEET_ID = 'claims-sheet';
const ORDER: ClaimVerdict[] = ['contradicted', 'not_found', 'partial', 'supported'];

function storedMessage(messageEl: HTMLElement): Message | undefined {
  const convId = useStore.getState().currentConversation?.id;
  return convId
    ? useStore.getState().getMessages(convId).find((m) => m.id === messageEl.dataset.messageId)
    : undefined;
}

/** "2 · example.cz" for a cited claim; "Source 2" when the source list is unknown. */
function citation(ann: ClaimAnnotation, sources: Source[] | null | undefined): string {
  if (!ann.source) return '';
  const url = sources?.[ann.source - 1]?.url;
  return url ? `${ann.source} · ${displayHost(url)}` : groundingStrings().sourceNumber(ann.source);
}

function row(ann: ClaimAnnotation, index: number, sources?: Source[] | null): HTMLButtonElement {
  const s = groundingStrings();
  const detail = ann.verdict === 'supported' ? citation(ann, sources) : (ann.reason ?? '');
  // An inline row: the spaces between verdict, quote and detail show
  return createElement('button', { type: 'button', class: 'claims-sheet__row', 'data-claim': String(index) }, [
    createElement('span', { class: `claims-sheet__verdict claims-sheet__verdict--${ann.verdict}` }, [
      s.verdictLabels[ann.verdict],
    ]),
    ' ',
    createElement('span', { class: 'claims-sheet__quote' }, [plainQuote(ann.quote)]),
    ...(detail ? [' ', createElement('span', { class: 'claims-sheet__detail' }, [detail])] : []),
  ]);
}

let opener: HTMLElement | null = null;

function closeClaimsSheet(restoreFocus = false): void {
  const sheet = document.getElementById(SHEET_ID);
  if (!sheet) return;
  sheet.remove();
  if (restoreFocus) opener?.focus();
  opener = null;
}

function flash(target: HTMLElement): void {
  target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
  target.classList.add('claim--flash');
  window.setTimeout(() => target.classList.remove('claim--flash'), CLAIM_FLASH_MS);
}

function openClaimsSheet(messageEl: HTMLElement): void {
  const annotations = getMessageAnnotations(messageEl);
  const grounding = getMessageGrounding(messageEl);
  if (!annotations?.length || !grounding) return;
  closeClaimCard();
  closeClaimsSheet();
  const stored = storedMessage(messageEl);
  const s = groundingStrings();
  const sourced = annotations.filter((a) => a.verdict === 'supported').length;
  const rows = annotations
    .map((ann, i) => ({ ann, i }))
    .sort((a, b) => ORDER.indexOf(a.ann.verdict) - ORDER.indexOf(b.ann.verdict) || a.i - b.i);
  const mobile = window.innerWidth < MOBILE_BREAKPOINT_PX;
  const sheet = document.createElement('div');
  sheet.id = SHEET_ID;
  sheet.className = `claims-sheet ${mobile ? 'claims-sheet--sheet' : 'claims-sheet--popover'}`;
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-modal', 'true');
  const meta =
    !grounding.legacy &&
    createElement('p', { class: 'claims-sheet__meta' }, [
      s.sheetMeta(grounding.source_count ?? 0, sourced, annotations.length),
    ]);
  sheet.append(
    createElement('div', { class: 'claims-sheet__backdrop' }),
    createElement('div', { class: 'claims-sheet__panel' }, [
      mobile && createElement('div', { class: 'claims-sheet__grab' }),
      createElement('h4', { class: 'claims-sheet__title' }, [s.sheetTitle]),
      meta,
      createElement(
        'div',
        { class: 'claims-sheet__rows' },
        rows.map(({ ann, i }) => row(ann, i, stored?.sources))
      ),
    ])
  );
  sheet.querySelector('.claims-sheet__backdrop')?.addEventListener('click', () => closeClaimsSheet(true));
  sheet.addEventListener('click', (e) => {
    const row = (e.target as Element).closest<HTMLElement>('.claims-sheet__row');
    if (!row) return;
    closeClaimsSheet();
    const target = messageEl.querySelector<HTMLElement>(`[data-claim="${row.dataset.claim}"]`);
    if (target) flash(target);
  });
  document.body.appendChild(sheet);
  const panel = sheet.querySelector<HTMLElement>('.claims-sheet__panel');
  if (mobile && panel) attachSheetDismiss(panel, () => closeClaimsSheet(true));
  opener = messageEl.querySelector<HTMLElement>('.grounding-footer');
  sheet.querySelector<HTMLElement>('.claims-sheet__row')?.focus();
  const footerEl = messageEl.querySelector('.grounding-footer');
  if (!mobile && footerEl && panel) {
    const footer = footerEl.getBoundingClientRect();
    panel.style.left = `${footer.left + window.scrollX}px`;
    panel.style.top = `${Math.max(16, footer.top + window.scrollY - panel.offsetHeight - 8)}px`;
  }
}

export function initClaimsSheet(): void {
  const messages = document.getElementById('messages');
  if (!messages) return;
  messages.addEventListener('click', (e) => {
    const footer = (e.target as Element).closest<HTMLElement>('.grounding-footer[role="button"]');
    if (!footer) return;
    const messageEl = footer.closest<HTMLElement>('.message');
    if (messageEl) openClaimsSheet(messageEl);
  });
  messages.addEventListener('keydown', (e) => {
    const footer = (e.target as Element).closest<HTMLElement>('.grounding-footer[role="button"]');
    if (footer && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      footer.click();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeClaimsSheet(true);
    // aria-modal: Tab cycles inside the open sheet (F9)
    const sheet = document.getElementById('claims-sheet');
    if (sheet) trapTabKey(sheet, e);
  });
}
