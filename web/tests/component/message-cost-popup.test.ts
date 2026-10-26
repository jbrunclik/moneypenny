import { beforeAll, describe, expect, it } from 'vitest';
import { initMessageCostPopup } from '@/components/MessageCostPopup';
import { createPopupShell } from '@/components/InfoPopup';
import type { MessageCostResponse } from '@/types/api';

const COST: MessageCostResponse = {
  message_id: 'm1',
  cost_usd: 0.00125,
  cost: 0.03,
  currency: 'CZK',
  formatted: '0.03 Kč',
  input_tokens: 12000,
  output_tokens: 345,
  model: 'gemini-test',
  image_generation_cost_usd: null,
  image_generation_cost: null,
  image_generation_cost_formatted: null,
};

const popup = () => document.getElementById('message-cost-popup')!;

function rows(): Record<string, string> {
  return Object.fromEntries(
    [...popup().querySelectorAll('tr')].map((tr) => [
      tr.querySelector('.message-cost-label')!.textContent,
      tr.querySelector('.message-cost-value')!.textContent,
    ])
  );
}

describe('MessageCostPopup', () => {
  beforeAll(() => {
    document.body.replaceChildren(createPopupShell('message-cost-popup'));
    initMessageCostPopup();
  });

  it('opens on its event with the cost breakdown', () => {
    window.dispatchEvent(new CustomEvent('message-cost:open', { detail: COST }));

    expect(popup().classList.contains('hidden')).toBe(false);
    expect(popup().querySelector('.dialog-title')!.textContent).toBe('Message Cost');
    expect(rows()).toEqual({
      'Cost:': '0.03 Kč',
      'Model:': 'gemini-test',
      'Input tokens:': (12000).toLocaleString(),
      'Output tokens:': (345).toLocaleString(),
      'Total tokens:': (12345).toLocaleString(),
      'Cost (USD):': '$0.001250',
    });
    expect(popup().querySelector('.message-cost-amount')!.textContent).toBe('0.03 Kč');
  });

  it('closes from its close button', () => {
    window.dispatchEvent(new CustomEvent('message-cost:open', { detail: COST }));
    popup().querySelector<HTMLElement>('.info-popup-close')!.click();
    expect(popup().classList.contains('hidden')).toBe(true);
  });
});
