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
import { displayHost, getMessageAnnotations } from './messages/annotations';
import { groundingStrings } from './messages/grounding-strings';

const CARD_ID = 'claim-card';
const TARGET_SELECTOR = '.claim, .claim-cite';
const GUTTER_PX = 16;
const CARD_GAP_PX = 6;
/** Used before the card has laid out (and in tests) */
const CARD_ESTIMATED_HEIGHT_PX = 160;
let hoverTimer: number | undefined;
let leaveTimer: number | undefined;
let openTarget: HTMLElement | null = null;
let openedByHover = false;

interface CardContext {
  ann: ClaimAnnotation;
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
    source: ann.source ? stored?.sources?.[ann.source - 1] : undefined,
  };
}

function sourceLine(ctx: CardContext): string {
  if (!ctx.ann.source) return '';
  const host = ctx.source ? displayHost(ctx.source.url) : `${ctx.ann.source}`;
  return `<span class="claim-card__source"><sup>${ctx.ann.source}</sup> ${escapeHtml(host)}</span>`;
}

/** The quote as it reads (no ** or link syntax) - for messages and lists. */
export function plainQuote(quote: string): string {
  return quote.replace(/\*\*|__|[*_`]|\]\([^)]*\)|[[\]]/g, '').trim();
}

function cardHtml(ctx: CardContext): string {
  const s = groundingStrings();
  const { ann } = ctx;
  const passage = ann.source_quote ? `<blockquote>„${escapeHtml(ann.source_quote)}“</blockquote>` : '';
  if (ann.verdict === 'supported') {
    const title = ctx.source ? ` <small>· ${escapeHtml(ctx.source.title)}</small>` : '';
    return `<div class="claim-card__heading claim-card__heading--cite">${sourceLine(ctx)}${title}</div>${passage}`;
  }
  // Converted old claims and downgraded ones carry no reason of their own
  const reason = ann.reason ?? s.defaultReason;
  return `
    <div class="claim-card__heading claim-card__heading--${ann.verdict}">${escapeHtml(s.headings[ann.verdict])}</div>
    ${reason ? `<p class="claim-card__reason">${escapeHtml(reason)}</p>` : ''}
    ${passage}${ann.verdict === 'contradicted' ? sourceLine(ctx) : ''}
    <button type="button" class="claim-card__lookup">${escapeHtml(s.lookUp)}</button>`;
}

/** Below the claim, or above it when the card would run under the composer. */
function position(card: HTMLElement, target: HTMLElement): void {
  const rect = target.getBoundingClientRect();
  const width = Math.min(card.offsetWidth || 320, window.innerWidth - 2 * GUTTER_PX);
  const height = card.offsetHeight || CARD_ESTIMATED_HEIGHT_PX;
  const composerTop = document.getElementById('input-container')?.getBoundingClientRect().top;
  const floor = Math.min(window.innerHeight, composerTop || window.innerHeight) - GUTTER_PX;
  const below = rect.bottom + CARD_GAP_PX;
  const top = below + height <= floor ? below : Math.max(GUTTER_PX, rect.top - CARD_GAP_PX - height);
  card.style.left = `${Math.min(Math.max(GUTTER_PX, rect.left), window.innerWidth - GUTTER_PX - width)}px`;
  card.style.top = `${top}px`;
}

export function closeClaimCard(restoreFocus = false): void {
  const opener = openTarget;
  window.clearTimeout(leaveTimer);
  openedByHover = false;
  document.getElementById(CARD_ID)?.remove();
  openTarget?.classList.remove('claim--open');
  openTarget?.removeAttribute('aria-describedby');
  openTarget = null;
  if (restoreFocus) opener?.focus();
}

export function openClaimCard(target: HTMLElement, focus = false): void {
  const ctx = contextFor(target);
  closeClaimCard();
  if (!ctx) return;
  const card = document.createElement('div');
  card.id = CARD_ID;
  card.className = 'claim-card';
  card.setAttribute('role', 'dialog');
  card.innerHTML = cardHtml(ctx);
  card.querySelector('.claim-card__lookup')?.addEventListener('click', () => {
    closeClaimCard();
    void sendComposedText(groundingStrings().lookUpMessage(plainQuote(ctx.ann.quote)));
  });
  // Moving from the claim into a hover-opened card keeps it open
  card.addEventListener('mouseenter', () => window.clearTimeout(leaveTimer));
  card.addEventListener('mouseleave', scheduleHoverClose);
  document.body.appendChild(card);
  position(card, target);
  target.classList.add('claim--open');
  target.setAttribute('aria-describedby', CARD_ID);
  openTarget = target;
  if (focus) {
    card.tabIndex = -1;
    (card.querySelector<HTMLElement>('.claim-card__lookup') ?? card).focus();
  }
}

/** A card the pointer opened closes shortly after the pointer leaves it. */
function scheduleHoverClose(): void {
  if (!openedByHover) return;
  window.clearTimeout(leaveTimer);
  leaveTimer = window.setTimeout(() => closeClaimCard(), CLAIM_CARD_HOVER_DELAY_MS);
}

function onClaimClick(e: MouseEvent): void {
  const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
  if (!target) return;
  window.clearTimeout(hoverTimer);
  if (target === openTarget && openedByHover) {
    // The click pins a card the hover already opened instead of closing it
    openedByHover = false;
    window.clearTimeout(leaveTimer);
  } else if (target === openTarget) {
    closeClaimCard();
  } else {
    openClaimCard(target, true);
  }
}

function initHover(messages: HTMLElement): void {
  messages.addEventListener('mouseover', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    window.clearTimeout(hoverTimer);
    if (target === openTarget) window.clearTimeout(leaveTimer);
    if (target && target !== openTarget) {
      hoverTimer = window.setTimeout(() => {
        openClaimCard(target);
        openedByHover = true;
      }, CLAIM_CARD_HOVER_DELAY_MS);
    }
  });
  messages.addEventListener('mouseout', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    if (!target) return;
    window.clearTimeout(hoverTimer);
    if (target === openTarget) scheduleHoverClose();
  });
}

export function initClaimCard(): void {
  const messages = document.getElementById('messages');
  if (!messages) return;
  messages.addEventListener('click', onClaimClick);
  messages.addEventListener('keydown', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    if (target && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      openClaimCard(target, true);
    }
  });
  if (window.matchMedia?.('(hover: hover)').matches) initHover(messages);
  // The card is fixed to the viewport; the list scrolling would leave it behind
  messages.addEventListener('scroll', () => closeClaimCard(), { passive: true });
  // Outside clicks close the card; the claim's own click must still reach
  // other document listeners (other popovers close on it), so it is not stopped
  document.addEventListener('click', (e) => {
    if (!(e.target as Element).closest(`${TARGET_SELECTOR}, #${CARD_ID}`)) closeClaimCard();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && openTarget) closeClaimCard(true);
  });
}
