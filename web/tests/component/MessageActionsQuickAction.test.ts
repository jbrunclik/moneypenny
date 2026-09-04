/**
 * "Save as quick action" button on user messages.
 */
import { describe, it, expect, vi } from 'vitest';
import { createMessageActions } from '@/components/messages/actions';

describe('message actions - save as quick action', () => {
  it('user messages get the button and it dispatches message:save-quick-action', () => {
    const actions = createMessageActions(
      'm1',
      '2026-09-04T10:00:00Z',
      undefined,
      undefined,
      'user'
    );
    const btn = actions.querySelector<HTMLButtonElement>('.message-save-quick-action-btn');
    expect(btn).not.toBeNull();
    const handler = vi.fn();
    document.addEventListener('message:save-quick-action', handler);
    btn!.click();
    expect(handler).toHaveBeenCalledTimes(1);
    expect((handler.mock.calls[0][0] as CustomEvent).detail).toEqual({ messageId: 'm1' });
    document.removeEventListener('message:save-quick-action', handler);
  });

  it('assistant messages do not get the button', () => {
    const actions = createMessageActions(
      'm2',
      '2026-09-04T10:00:00Z',
      undefined,
      undefined,
      'assistant'
    );
    expect(actions.querySelector('.message-save-quick-action-btn')).toBeNull();
  });
});
