/**
 * Every claim of one answer, problems first. Bottom sheet on mobile, popover
 * on desktop; a row scrolls to the claim in the answer and flashes it.
 */
import { CLAIM_FLASH_MS, MOBILE_BREAKPOINT_PX } from '../config';
import { useStore } from '../state/store';
import type { ClaimAnnotation, ClaimVerdict, Message, Source } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { closeClaimCard, plainQuote } from './ClaimCard';
import { displayHost, getMessageAnnotations, getMessageGrounding, getMessageLanguage } from './messages/annotations';
import { groundingStrings } from './messages/grounding-strings';

const SHEET_ID = 'claims-sheet';
const ORDER: ClaimVerdict[] = ['contradicted', 'not_found', 'partial', 'supported'];

function storedMessage(messageEl: HTMLElement): Message | undefined {
  const convId = useStore.getState().currentConversation?.id;
  return convId
    ? useStore.getState().getMessages(convId).find((m) => m.id === messageEl.dataset.messageId)
    : undefined;
}

/** "2 · example.cz" for a cited claim (the domain when the source is known). */
function citation(ann: ClaimAnnotation, sources: Source[] | undefined): string {
  if (!ann.source) return '';
  const url = sources?.[ann.source - 1]?.url;
  return url ? `${ann.source} · ${displayHost(url)}` : `${ann.source}`;
}

function rowHtml(ann: ClaimAnnotation, index: number, language?: string, sources?: Source[]): string {
  const s = groundingStrings(language);
  const detail = ann.verdict === 'supported' ? citation(ann, sources) : (ann.reason ?? '');
  return `<button type="button" class="claims-sheet__row" data-claim="${index}">
      <span class="claims-sheet__verdict claims-sheet__verdict--${ann.verdict}">${escapeHtml(s.verdictLabels[ann.verdict])}</span>
      <span class="claims-sheet__quote">${escapeHtml(plainQuote(ann.quote))}</span>
      ${detail ? `<span class="claims-sheet__detail">${escapeHtml(detail)}</span>` : ''}
    </button>`;
}

let opener: HTMLElement | null = null;

export function closeClaimsSheet(restoreFocus = false): void {
  const sheet = document.getElementById(SHEET_ID);
  if (!sheet) return;
  sheet.remove();
  if (restoreFocus) opener?.focus();
  opener = null;
}

function flash(target: HTMLElement): void {
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.add('claim--flash');
  window.setTimeout(() => target.classList.remove('claim--flash'), CLAIM_FLASH_MS);
}

export function openClaimsSheet(messageEl: HTMLElement): void {
  const annotations = getMessageAnnotations(messageEl);
  const grounding = getMessageGrounding(messageEl);
  if (!annotations?.length || !grounding) return;
  closeClaimCard();
  closeClaimsSheet();
  const stored = storedMessage(messageEl);
  const language = getMessageLanguage(messageEl) ?? stored?.language;
  const s = groundingStrings(language);
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
  const meta = grounding.legacy ? '' : `<p class="claims-sheet__meta">${escapeHtml(s.sheetMeta(grounding.source_count ?? 0, sourced, annotations.length))}</p>`;
  sheet.innerHTML = `<div class="claims-sheet__backdrop"></div>
    <div class="claims-sheet__panel">
      ${mobile ? '<div class="claims-sheet__grab"></div>' : ''}
      <h4 class="claims-sheet__title">${escapeHtml(s.sheetTitle)}</h4>${meta}
      <div class="claims-sheet__rows">${rows.map(({ ann, i }) => rowHtml(ann, i, language, stored?.sources)).join('')}</div>
    </div>`;
  sheet.querySelector('.claims-sheet__backdrop')!.addEventListener('click', () => closeClaimsSheet(true));
  sheet.addEventListener('click', (e) => {
    const row = (e.target as Element).closest<HTMLElement>('.claims-sheet__row');
    if (!row) return;
    closeClaimsSheet();
    const target = messageEl.querySelector<HTMLElement>(`[data-claim="${row.dataset.claim}"]`);
    if (target) flash(target);
  });
  document.body.appendChild(sheet);
  opener = messageEl.querySelector<HTMLElement>('.grounding-footer');
  sheet.querySelector<HTMLElement>('.claims-sheet__row')?.focus();
  if (!mobile) {
    const footer = messageEl.querySelector('.grounding-footer')!.getBoundingClientRect();
    const panel = sheet.querySelector<HTMLElement>('.claims-sheet__panel')!;
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
  });
}
