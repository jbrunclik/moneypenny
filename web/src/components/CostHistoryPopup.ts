import { createPopup, createPopupHtml, type PopupInstance } from './InfoPopup';
import type { CostHistoryResponse } from '../types/api';
import { createElement } from '../utils/dom';
import { COST_HISTORY_ICON } from '../utils/icons';

const POPUP_ID = 'cost-history-popup';
const EVENT_NAME = 'cost-history:open';

/**
 * The cost history table
 */
function costHistory(data: CostHistoryResponse): HTMLElement[] {
  if (!data.history || data.history.length === 0) {
    return [
      createElement('div', { class: 'cost-history-empty' }, [
        createElement('p', {}, ['No cost history available yet.']),
        createElement('p', { class: 'text-muted' }, ['Costs will appear here as you use the chatbot.']),
      ]),
    ];
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

  const rows = sortedHistory.map((month) => {
    const monthName = monthNames[month.month - 1];
    return createElement('tr', {}, [
      createElement('td', {}, [`${monthName ?? ''} ${month.year}`]),
      createElement('td', { class: 'cost-amount' }, [month.formatted]),
      createElement('td', { class: 'cost-messages' }, [String(month.message_count)]),
    ]);
  });

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

  const strong = (text: string): HTMLElement => createElement('strong', {}, [text]);
  const th = (text: string): HTMLElement => createElement('th', {}, [text]);
  return [
    createElement('div', { class: 'cost-history-content' }, [
      createElement('table', { class: 'cost-history-table' }, [
        createElement('thead', {}, [createElement('tr', {}, [th('Month'), th('Cost'), th('Messages')])]),
        createElement('tbody', {}, rows),
        createElement('tfoot', {}, [
          createElement('tr', { class: 'cost-history-total' }, [
            createElement('td', {}, [strong('Total')]),
            createElement('td', { class: 'cost-amount' }, [strong(totalFormatted)]),
            createElement('td', { class: 'cost-messages' }, [
              strong(String(data.history.reduce((sum, m) => sum + m.message_count, 0))),
            ]),
          ]),
        ]),
      ]),
    ]),
  ];
}

/**
 * Cost history popup instance
 */
export const costHistoryPopup: PopupInstance<CostHistoryResponse> = createPopup(
  {
    id: POPUP_ID,
    eventName: EVENT_NAME,
    icon: COST_HISTORY_ICON,
    title: 'Cost History',
    styleClass: 'cost-history',
  },
  costHistory
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

