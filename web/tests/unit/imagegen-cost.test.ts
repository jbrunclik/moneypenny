/**
 * The image generation popup fills its cost placeholder from the message
 * cost, and drops it when there is no message, no image cost or an error.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';

const getMessageCost = vi.hoisted(() => vi.fn());
vi.mock('@/api/costs', () => ({ costs: { getMessageCost } }));
vi.mock('@/components/InfoPopup', () => ({ createPopup: () => ({ init: vi.fn(), open: vi.fn() }) }));

import { initImageGenPopup } from '@/components/ImageGenPopup';

function open(detail: unknown): void {
  window.dispatchEvent(new CustomEvent('imagegen:open', { detail }));
}

const placeholder = () => document.getElementById('imagegen-cost-placeholder');

describe('image generation cost', () => {
  beforeAll(() => {
    initImageGenPopup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="popup"><div id="imagegen-cost-placeholder"></div></div>';
  });

  it('shows the image generation cost of the message', async () => {
    getMessageCost.mockResolvedValue({ image_generation_cost_formatted: '$0.04' });
    open([{ message_id: 'm1' }]);

    await vi.waitFor(() => expect(document.querySelector('.imagegen-cost-value')?.textContent).toBe('$0.04'));
    expect(getMessageCost).toHaveBeenCalledWith('m1');
    expect(placeholder()).toBeNull();
  });

  it('drops the placeholder when the message has no image cost', async () => {
    getMessageCost.mockResolvedValue({ image_generation_cost_formatted: null });
    open([{ message_id: 'm1' }]);

    await vi.waitFor(() => expect(placeholder()).toBeNull());
    expect(document.querySelector('.imagegen-cost')).toBeNull();
  });

  it('drops the placeholder when the cost request fails', async () => {
    getMessageCost.mockRejectedValue(new Error('down'));
    open([{ message_id: 'm1' }]);

    await vi.waitFor(() => expect(placeholder()).toBeNull());
  });

  it('drops the placeholder without a message id, without asking', () => {
    open([{}]);

    expect(placeholder()).toBeNull();
    expect(getMessageCost).not.toHaveBeenCalled();
  });
});
