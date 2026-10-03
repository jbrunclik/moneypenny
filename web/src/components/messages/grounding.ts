/** Footer and decoration for grounding-checked assistant messages. */
import type { ClaimAnnotation, GroundingSummary, Message } from '../../types/api';
import { applyAnnotations, rememberAnnotations } from './annotations';
import { groundingStrings } from './grounding-strings';

const FOOTER_CLASS = 'grounding-footer';

export function footerText(annotations: ClaimAnnotation[], grounding: GroundingSummary): string {
  const s = groundingStrings();
  const count = (v: ClaimAnnotation['verdict']) => annotations.filter((a) => a.verdict === v).length;
  const parts: string[] = [];
  if (!grounding.legacy) parts.push(s.ofSourced(count('supported'), annotations.length));
  if (count('not_found')) parts.push(s.unsourced(count('not_found')));
  if (count('partial')) parts.push(s.partial(count('partial')));
  if (count('contradicted')) parts.push(s.contradicted(count('contradicted')));
  return parts.join(' · ');
}

function placeFooter(messageEl: HTMLElement): HTMLElement | null {
  const content = messageEl.querySelector('.message-content');
  if (!content) return null;
  messageEl.querySelector(`.${FOOTER_CLASS}`)?.remove();
  const footer = document.createElement('div');
  footer.className = FOOTER_CLASS;
  content.after(footer);
  return footer;
}

export function showGroundingChecking(messageEl: HTMLElement): void {
  const footer = placeFooter(messageEl);
  if (!footer) return;
  footer.classList.add(`${FOOTER_CLASS}--checking`);
  footer.textContent = groundingStrings().checking;
}

export function decorateGrounding(
  messageEl: HTMLElement,
  message: Pick<Message, 'annotations' | 'grounding'>
): void {
  const annotations = message.annotations ?? [];
  if (!annotations.length || !message.grounding) {
    messageEl.querySelector(`.${FOOTER_CLASS}`)?.remove();
    return;
  }
  const content = messageEl.querySelector<HTMLElement>('.message-content');
  if (content) applyAnnotations(content, annotations);
  rememberAnnotations(messageEl, annotations, message.grounding);
  const footer = placeFooter(messageEl);
  if (!footer) return;
  footer.textContent = footerText(annotations, message.grounding);
  if (annotations.some((a) => a.verdict !== 'supported')) {
    footer.setAttribute('role', 'button');
    footer.tabIndex = 0;
  }
}
