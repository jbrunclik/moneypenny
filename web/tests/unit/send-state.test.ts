/**
 * Send-state chrome on user messages: pending/failed classes, the "Not sent"
 * row, and its retry/discard buttons dispatching outbox events.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { applySendState, createSendFailedActions, setMessageSendState } from '@/components/messages/send-state';

const PENDING = 'message--send-pending';
const FAILED = 'message--send-failed';

function mountMessage(id: string): { message: HTMLElement; wrapper: HTMLElement } {
  const message = document.createElement('div');
  message.className = 'message user';
  message.dataset.messageId = id;
  const wrapper = document.createElement('div');
  wrapper.className = 'message-content-wrapper';
  message.appendChild(wrapper);
  document.body.appendChild(message);
  return { message, wrapper };
}

describe('send state', () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  describe('createSendFailedActions', () => {
    const listener = vi.fn();
    beforeEach(() => {
      listener.mockClear();
      document.addEventListener('outbox:retry', listener);
      document.addEventListener('outbox:discard', listener);
    });
    afterEach(() => {
      document.removeEventListener('outbox:retry', listener);
      document.removeEventListener('outbox:discard', listener);
    });

    it('renders a "Not sent" label with Retry and Discard buttons', () => {
      const row = createSendFailedActions('m1');
      expect(row.querySelector('.send-status-label')?.textContent).toContain('Not sent');
      const actions = [...row.querySelectorAll<HTMLButtonElement>('button')].map((b) => b.dataset.action);
      expect(actions).toEqual(['retry-send', 'discard-send']);
    });

    it.each([
      ['retry-send', 'outbox:retry'],
      ['discard-send', 'outbox:discard'],
    ])('a click on %s dispatches %s with the message id', (action, eventName) => {
      const row = createSendFailedActions('m1');
      document.body.appendChild(row);
      row.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)?.click();
      expect(listener).toHaveBeenCalledTimes(1);
      const event = listener.mock.calls[0]?.[0] as CustomEvent<{ messageId: string }>;
      expect(event.type).toBe(eventName);
      expect(event.detail).toEqual({ messageId: 'm1' });
    });

    it('a click on the label dispatches nothing', () => {
      const row = createSendFailedActions('m1');
      document.body.appendChild(row);
      row.querySelector<HTMLElement>('.send-status-label')?.click();
      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe('applySendState', () => {
    it('does nothing for a delivered message', () => {
      const { message, wrapper } = mountMessage('m1');
      applySendState(message, wrapper, 'm1', undefined);
      expect(message.classList.contains(PENDING)).toBe(false);
      expect(message.classList.contains(FAILED)).toBe(false);
      expect(wrapper.children).toHaveLength(0);
    });

    it('marks a pending message without the failure row', () => {
      const { message, wrapper } = mountMessage('m1');
      applySendState(message, wrapper, 'm1', 'pending');
      expect(message.classList.contains(PENDING)).toBe(true);
      expect(wrapper.querySelector('.message-send-status')).toBeNull();
    });

    it('marks a failed message and adds the failure row', () => {
      const { message, wrapper } = mountMessage('m1');
      applySendState(message, wrapper, 'm1', 'failed');
      expect(message.classList.contains(FAILED)).toBe(true);
      expect(wrapper.querySelector('.message-send-status')).not.toBeNull();
    });
  });

  describe('setMessageSendState', () => {
    it('moves pending -> failed -> sent, adding then removing the failure row', () => {
      const { message } = mountMessage('m1');
      setMessageSendState('m1', 'pending');
      expect(message.classList.contains(PENDING)).toBe(true);

      setMessageSendState('m1', 'failed');
      expect(message.classList.contains(PENDING)).toBe(false);
      expect(message.classList.contains(FAILED)).toBe(true);
      expect(message.querySelectorAll('.message-send-status')).toHaveLength(1);

      setMessageSendState('m1', 'sent');
      expect(message.classList.contains(FAILED)).toBe(false);
      expect(message.querySelector('.message-send-status')).toBeNull();
    });

    it('failing twice keeps a single failure row', () => {
      const { message } = mountMessage('m1');
      setMessageSendState('m1', 'failed');
      setMessageSendState('m1', 'failed');
      expect(message.querySelectorAll('.message-send-status')).toHaveLength(1);
    });

    it('sent enables the lightbox on pending images', () => {
      const { wrapper } = mountMessage('m1');
      const img = document.createElement('img');
      img.dataset.pending = 'true';
      wrapper.appendChild(img);
      setMessageSendState('m1', 'sent');
      expect(img.dataset.pending).toBeUndefined();
    });

    it('ignores a message that is not rendered', () => {
      expect(() => setMessageSendState('missing', 'failed')).not.toThrow();
    });
  });
});
