import { createPopup, createPopupHtml, type PopupInstance } from './InfoPopup';
import type { CostHistoryResponse } from '../types/api';
import { escapeHtml } from '../utils/dom';

const POPUP_ID = 'cost-history-popup';
const EVENT_NAME = 'cost-history:open';

/**
 * Render cost history content
 */
function renderCostHistory(data: CostHistoryResponse): string {
  if (!data.history || data.history.length === 0) {
    return `
      <div class="cost-history-empty">
        <p>No cost history available yet.</p>
        <p class="text-muted">Costs will appear here as you use the chatbot.</p>
      </div>
    `;
  }

  const monthNames = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  // Sort from current month to oldest (reverse chronological)
  const sortedHistory = [...data.history].sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;
    return b.month - a.month;
  });

  const rows = sortedHistory.map(month => {
    const monthName = monthNames[month.month - 1];
    return `
      <tr>
        <td>${escapeHtml(monthName ?? '')} ${month.year}</td>
        <td class="cost-amount">${escapeHtml(month.formatted)}</td>
        <td class="cost-messages">${month.message_count}</td>
      </tr>
    `;
  }).join('');

  const total = data.history.reduce((sum, month) => sum + (month.total || 0), 0);
  const currency = data.history[0]?.currency || 'USD';
  // Use the same formatting logic as backend (format_cost function)
  // Match the precision: 4 decimals for USD/EUR/GBP, 2 for CZK
  let totalFormatted: string;
  if (currency === 'USD') {
    totalFormatted = `$${total.toFixed(4)}`;
  } else if (currency === 'CZK') {
    totalFormatted = `${total.toFixed(2)} Kč`;
  } else if (currency === 'EUR') {
    totalFormatted = `€${total.toFixed(4)}`;
  } else if (currency === 'GBP') {
    totalFormatted = `£${total.toFixed(4)}`;
  } else {
    totalFormatted = `${total.toFixed(4)} ${currency}`;
  }

  return `
    <div class="cost-history-content">
      <table class="cost-history-table">
        <thead>
          <tr>
            <th>Month</th>
            <th>Cost</th>
            <th>Messages</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
        <tfoot>
          <tr class="cost-history-total">
            <td><strong>Total</strong></td>
            <td class="cost-amount"><strong>${escapeHtml(totalFormatted)}</strong></td>
            <td class="cost-messages">
              <strong>${data.history.reduce((sum, m) => sum + m.message_count, 0)}</strong>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  `;
}

/**
 * Cost history popup instance
 */
export const costHistoryPopup: PopupInstance<CostHistoryResponse> = createPopup(
  {
    id: POPUP_ID,
    eventName: EVENT_NAME,
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
    title: 'Cost History',
    styleClass: 'cost-history',
  },
  renderCostHistory
);

/**
 * Get HTML for cost history popup
 */
export function getCostHistoryPopupHtml(): string {
  return createPopupHtml(POPUP_ID);
}

/**
 * Open cost history popup with data
 */
export function openCostHistory(data: CostHistoryResponse): void {
  costHistoryPopup.open(data);
}

