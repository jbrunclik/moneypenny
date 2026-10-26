import type { MessageCostResponse } from '../types/api';
import { createElement } from '../utils/dom';
import { COST_ICON } from '../utils/icons';
import { createPopup, type PopupInstance } from './InfoPopup';

/** A label/value row of a two-column info table. */
function row(label: string, value: string, valueClass = ''): HTMLTableRowElement {
  return createElement('tr', {}, [
    createElement('td', { class: 'message-cost-label' }, [label]),
    createElement('td', { class: `message-cost-value${valueClass}` }, [value]),
  ]);
}

/**
 * The message cost table
 */
function messageCost(data: MessageCostResponse): HTMLElement[] {
  return [
    createElement('div', { class: 'message-cost-content' }, [
      createElement('table', { class: 'message-cost-table' }, [
        createElement('tbody', {}, [
          row('Cost:', data.formatted, ' message-cost-amount'),
          row('Model:', data.model),
          row('Input tokens:', data.input_tokens.toLocaleString()),
          row('Output tokens:', data.output_tokens.toLocaleString()),
          row('Total tokens:', (data.input_tokens + data.output_tokens).toLocaleString()),
          row('Cost (USD):', `$${data.cost_usd.toFixed(6)}`),
        ]),
      ]),
    ]),
  ];
}

// Create the message cost popup instance
const messageCostPopup: PopupInstance<MessageCostResponse> = createPopup<MessageCostResponse>(
  {
    id: 'message-cost-popup',
    eventName: 'message-cost:open',
    icon: COST_ICON,
    title: 'Message Cost',
    styleClass: 'message-cost',
  },
  messageCost
);

/**
 * Initialize message cost popup event handlers
 */
export function initMessageCostPopup(): void {
  messageCostPopup.init();
}

