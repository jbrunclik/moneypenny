import type { MessageCostResponse } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { COST_ICON } from '../utils/icons';
import { createPopup, type PopupInstance } from './InfoPopup';

/**
 * Render message cost info HTML
 */
function renderMessageCost(data: MessageCostResponse): string {
  return `
    <div class="message-cost-content">
      <table class="message-cost-table">
        <tbody>
          <tr>
            <td class="message-cost-label">Cost:</td>
            <td class="message-cost-value message-cost-amount">${escapeHtml(data.formatted)}</td>
          </tr>
          <tr>
            <td class="message-cost-label">Model:</td>
            <td class="message-cost-value">${escapeHtml(data.model)}</td>
          </tr>
          <tr>
            <td class="message-cost-label">Input tokens:</td>
            <td class="message-cost-value">${data.input_tokens.toLocaleString()}</td>
          </tr>
          <tr>
            <td class="message-cost-label">Output tokens:</td>
            <td class="message-cost-value">${data.output_tokens.toLocaleString()}</td>
          </tr>
          <tr>
            <td class="message-cost-label">Total tokens:</td>
            <td class="message-cost-value">${(data.input_tokens + data.output_tokens).toLocaleString()}</td>
          </tr>
          <tr>
            <td class="message-cost-label">Cost (USD):</td>
            <td class="message-cost-value">$${data.cost_usd.toFixed(6)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
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
  renderMessageCost
);

/**
 * Initialize message cost popup event handlers
 */
export function initMessageCostPopup(): void {
  messageCostPopup.init();
}

