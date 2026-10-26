import { beforeEach, describe, expect, it } from 'vitest';
import { createCostHistoryPopupShell, openCostHistory } from '@/components/CostHistoryPopup';
import type { CostHistoryResponse } from '@/types/api';

type Month = CostHistoryResponse['history'][number];

function month(year: number, m: number, total: number, messages: number, currency = 'CZK'): Month {
  return { year, month: m, total_usd: total / 25, total, currency, formatted: `${total.toFixed(2)} Kč`, message_count: messages };
}

const popup = () => document.getElementById('cost-history-popup')!;
const bodyRows = () =>
  [...popup().querySelectorAll('tbody tr')].map((tr) => [...tr.children].map((td) => td.textContent));
const totalRow = () => [...popup().querySelector('.cost-history-total')!.children].map((td) => td.textContent);

describe('CostHistoryPopup', () => {
  beforeEach(() => {
    document.body.replaceChildren(createCostHistoryPopupShell());
  });

  it('lists months newest first with a total row', () => {
    openCostHistory({
      user_id: 'u1',
      history: [month(2026, 8, 100, 10), month(2026, 10, 50.5, 4), month(2025, 12, 20, 2)],
    });

    expect(popup().classList.contains('hidden')).toBe(false);
    expect(bodyRows()).toEqual([
      ['October 2026', '50.50 Kč', '4'],
      ['August 2026', '100.00 Kč', '10'],
      ['December 2025', '20.00 Kč', '2'],
    ]);
    expect(totalRow()).toEqual(['Total', '170.50 Kč', '16']);
  });

  it.each([
    ['USD', '$1.5000'],
    ['EUR', '€1.5000'],
    ['GBP', '£1.5000'],
    ['CHF', '1.5000 CHF'],
  ])('formats a %s total like the backend', (currency, formatted) => {
    openCostHistory({ user_id: 'u1', history: [month(2026, 1, 1, 1, currency), month(2026, 2, 0.5, 1, currency)] });
    expect(totalRow()[1]).toBe(formatted);
  });

  it('explains an empty history', () => {
    openCostHistory({ user_id: 'u1', history: [] });
    expect(popup().querySelector('table')).toBeNull();
    expect(popup().querySelector('.cost-history-empty')!.textContent).toContain('No cost history available yet.');
  });
});
