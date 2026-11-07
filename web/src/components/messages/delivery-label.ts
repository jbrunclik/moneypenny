/**
 * The small label above an assistant turn a scheduled item delivered into its
 * chat ("Check-in · Fri 18:00", "Watcher · found"), and the kind icons the
 * chat chip and the Command Center lane share.
 */
import type { MessageDelivery } from '../../types/api';
import { createElement } from '../../utils/dom';
import { BELL_ICON, CLOCK_ICON, HISTORY_ICON, SEARCH_ICON, createIconElement, type IconHtml } from '../../utils/icons';

export const SCHEDULE_KIND_ICONS: Record<MessageDelivery['kind'], IconHtml> = {
  reminder: BELL_ICON,
  check_in: CLOCK_ICON,
  watcher: SEARCH_ICON,
  recurring: HISTORY_ICON,
};

export function renderDeliveryLabel(delivery: MessageDelivery): HTMLElement {
  return createElement('div', { class: 'message-delivery' }, [
    createIconElement('message-delivery-icon', SCHEDULE_KIND_ICONS[delivery.kind]),
    createElement('span', { class: 'message-delivery-text' }, [delivery.label]),
  ]);
}
