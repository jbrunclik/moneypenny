import { describe, expect, it, vi } from 'vitest';

const sent: string[] = [];
vi.mock('@/core/messaging', () => ({
  sendMessage: vi.fn(async () => {
    const box = document.getElementById('message-input') as HTMLTextAreaElement;
    sent.push(box.value);
    box.value = '';
  }),
}));

import { sendComposedText } from '@/core/quick-actions';

describe('sendComposedText', () => {
  it('sends the text and puts back a draft the user was typing', async () => {
    document.body.innerHTML = '<textarea id="message-input"></textarea>';
    const box = document.getElementById('message-input') as HTMLTextAreaElement;
    box.value = 'my half-written question';

    await sendComposedText('Look up and verify: VeloRama');

    expect(sent).toEqual(['Look up and verify: VeloRama']);
    expect(box.value).toBe('my half-written question');
  });
});
