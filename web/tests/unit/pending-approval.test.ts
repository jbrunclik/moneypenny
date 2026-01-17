/**
 * Tests for pending approval detection in messages.
 */

import { describe, it, expect } from 'vitest';
import { hasPendingApproval } from '../../src/components/messages/render';
import type { Message } from '../../src/types/api';

const createMessage = (role: 'user' | 'assistant', content: string, id?: string): Message => ({
  id: id || `msg-${Date.now()}`,
  role,
  content,
  created_at: new Date().toISOString(),
});

describe('hasPendingApproval', () => {
  it('should return false for empty messages', () => {
    expect(hasPendingApproval([])).toBe(false);
  });

  it('should return false for regular conversation', () => {
    const messages: Message[] = [
      createMessage('user', 'Hello'),
      createMessage('assistant', 'Hi there! How can I help you?'),
    ];
    expect(hasPendingApproval(messages)).toBe(false);
  });

  it('should return true when last assistant message is approval request', () => {
    const messages: Message[] = [
      createMessage('user', '[Scheduled run at 2026-01-17 10:00 UTC]'),
      createMessage(
        'assistant',
        `[approval-request:abc12345-1234-5678-abcd-1234567890ab]
I need your permission to: **Add task: Buy groceries**

Tool: \`todoist_add_task\``
      ),
    ];
    expect(hasPendingApproval(messages)).toBe(true);
  });

  it('should return false when approval has been resolved', () => {
    const messages: Message[] = [
      createMessage('user', '[Scheduled run at 2026-01-17 10:00 UTC]'),
      createMessage(
        'assistant',
        `[approval-request:abc12345-1234-5678-abcd-1234567890ab]
I need your permission to: **Add task: Buy groceries**

Tool: \`todoist_add_task\``
      ),
      createMessage('user', '[Action approved: Add task: Buy groceries]'),
      createMessage('assistant', 'Great! I have added the task "Buy groceries" to your Todoist.'),
    ];
    expect(hasPendingApproval(messages)).toBe(false);
  });

  it('should return false when action was approved (even without follow-up assistant message)', () => {
    const messages: Message[] = [
      createMessage('user', '[Scheduled run at 2026-01-17 10:00 UTC]'),
      createMessage(
        'assistant',
        `[approval-request:abc12345-1234-5678-abcd-1234567890ab]
I need your permission to: **Add task: Buy groceries**

Tool: \`todoist_add_task\``
      ),
      createMessage('user', '[Action approved: Add task: Buy groceries]'),
    ];
    expect(hasPendingApproval(messages)).toBe(false);
  });

  it('should handle approval message without tool specification', () => {
    const messages: Message[] = [
      createMessage('user', '[Scheduled run at 2026-01-17 10:00 UTC]'),
      createMessage(
        'assistant',
        `[approval-request:abc12345-1234-5678-abcd-1234567890ab]
I need your permission to: **Send email to team**`
      ),
    ];
    expect(hasPendingApproval(messages)).toBe(true);
  });

  it('should return false for regular assistant message after trigger', () => {
    const messages: Message[] = [
      createMessage('user', '[Scheduled run at 2026-01-17 10:00 UTC]'),
      createMessage('assistant', 'Good morning! Here is your daily summary...'),
    ];
    expect(hasPendingApproval(messages)).toBe(false);
  });

  it('should handle multiple messages including user follow-ups', () => {
    const messages: Message[] = [
      createMessage('user', '[Scheduled run at 2026-01-17 10:00 UTC]'),
      createMessage('assistant', 'Starting your daily planner check...'),
      createMessage('user', 'Can you also check my calendar?'),
      createMessage(
        'assistant',
        `[approval-request:abc12345-1234-5678-abcd-1234567890ab]
I need your permission to: **Create calendar event**

Tool: \`google_calendar_create_event\``
      ),
    ];
    expect(hasPendingApproval(messages)).toBe(true);
  });
});
