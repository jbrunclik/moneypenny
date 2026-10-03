/**
 * Card for a grounding claim or source number: verdict, reason, the source
 * passage, and "Dohledat" (sends a targeted follow-up). One delegated handler
 * on #messages; hover opens on devices that hover, tap/click everywhere.
 */
import { CLAIM_CARD_HOVER_DELAY_MS } from '../config';
import { sendComposedText } from '../core/quick-actions';
import { useStore } from '../state/store';
import type { ClaimAnnotation, Source } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { getMessageAnnotations, getMessageGrounding, getMessageLanguage } from './messages/annotations';
import { groundingStrings } from './messages/grounding-strings';

const CARD_ID = 'claim-card';
const TARGET_SELECTOR = '.claim, .claim-cite';
const GUTTER_PX = 16;
let hoverTimer: number | undefined;
let openTarget: HTMLElement | null = null;

interface CardContext {
  ann: ClaimAnnotation;
  language?: string;
  legacy: boolean;
  source?: Source;
}

function contextFor(target: HTMLElement): CardContext | null {
  const messageEl = target.closest<HTMLElement>('.message');
  const index = Number(target.dataset.claim);
  const ann = messageEl ? getMessageAnnotations(messageEl)?.[index] : undefined;
  if (!messageEl || !ann) return null;
  const convId = useStore.getState().currentConversation?.id;
  const stored = convId ? useStore.getState().getMessages(convId).find((m) => m.id === messageEl.dataset.messageId) : undefined;
  return {
    ann,
    language: getMessageLanguage(messageEl) ?? stored?.language,
    legacy: Boolean(getMessageGrounding(messageEl)?.legacy),
    source: ann.source ? stored?.sources?.[ann.source - 1] : undefined,
  };
}

function sourceLine(ctx: CardContext): string {
  if (!ctx.ann.source) return '';
  const host = ctx.source ? new URL(ctx.source.url).hostname.replace(/^www\./, '') : `${ctx.ann.source}`;
  return `<span class="claim-card__source"><sup>${ctx.ann.source}</sup> ${escapeHtml(host)}</span>`;
}

function cardHtml(ctx: CardContext): string {
  const s = groundingStrings(ctx.language);
  const { ann } = ctx;
  const passage = ann.source_quote ? `<blockquote>„${escapeHtml(ann.source_quote)}“</blockquote>` : '';
  if (ann.verdict === 'supported') {
    const title = ctx.source ? ` <small>· ${escapeHtml(ctx.source.title)}</small>` : '';
    return `<div class="claim-card__heading claim-card__heading--cite">${sourceLine(ctx)}${title}</div>${passage}`;
  }
  const reason = ann.reason ?? (ctx.legacy ? s.legacyReason : '');
  return `
    <div class="claim-card__heading claim-card__heading--${ann.verdict}">${escapeHtml(s.headings[ann.verdict])}</div>
    ${reason ? `<p class="claim-card__reason">${escapeHtml(reason)}</p>` : ''}
    ${passage}${ann.verdict === 'contradicted' ? sourceLine(ctx) : ''}
    <button type="button" class="claim-card__lookup">${escapeHtml(s.lookUp)}</button>`;
}

function position(card: HTMLElement, target: HTMLElement): void {
  const rect = target.getBoundingClientRect();
  const width = Math.min(card.offsetWidth || 320, window.innerWidth - 2 * GUTTER_PX);
  const left = Math.min(Math.max(GUTTER_PX, rect.left), window.innerWidth - GUTTER_PX - width);
  card.style.left = `${left + window.scrollX}px`;
  card.style.top = `${rect.bottom + window.scrollY + 6}px`;
}

export function closeClaimCard(): void {
  document.getElementById(CARD_ID)?.remove();
  openTarget?.classList.remove('claim--open');
  openTarget?.removeAttribute('aria-describedby');
  openTarget = null;
}

export function openClaimCard(target: HTMLElement): void {
  const ctx = contextFor(target);
  closeClaimCard();
  if (!ctx) return;
  const card = document.createElement('div');
  card.id = CARD_ID;
  card.className = 'claim-card';
  card.setAttribute('role', 'dialog');
  card.innerHTML = cardHtml(ctx);
  card.querySelector('.claim-card__lookup')?.addEventListener('click', (e) => {
    e.stopPropagation();
    closeClaimCard();
    void sendComposedText(groundingStrings(ctx.language).lookUpMessage(ctx.ann.quote));
  });
  card.addEventListener('click', (e) => e.stopPropagation());
  document.body.appendChild(card);
  position(card, target);
  target.classList.add('claim--open');
  target.setAttribute('aria-describedby', CARD_ID);
  openTarget = target;
}

export function initClaimCard(): void {
  const messages = document.getElementById('messages');
  if (!messages) return;
  messages.addEventListener('click', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    if (!target) return;
    e.stopPropagation();
    if (target === openTarget) closeClaimCard();
    else openClaimCard(target);
  });
  messages.addEventListener('keydown', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    if (target && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      openClaimCard(target);
    }
  });
  if (window.matchMedia?.('(hover: hover)').matches) {
    messages.addEventListener('mouseover', (e) => {
      const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
      window.clearTimeout(hoverTimer);
      if (target && target !== openTarget) {
        hoverTimer = window.setTimeout(() => openClaimCard(target), CLAIM_CARD_HOVER_DELAY_MS);
      }
    });
  }
  document.addEventListener('click', closeClaimCard);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeClaimCard();
  });
}
