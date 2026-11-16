/**
 * A failed send goes out once even when two resends overlap: a Retry tapped
 * while its attachments still load from IndexedDB (no request registered
 * yet), or a second tab's automatic resend at the same moment (the server's
 * duplicate check reads before it inserts). Nov 16 2026.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const pending: Array<() => void> = [];
const releaseRestore = (): void => pending.splice(0).forEach((resolve) => resolve());
vi.mock('@/core/outbox', () => ({
  removeOutboxEntry: vi.fn(),
  restoreOutboxEntry: vi.fn(async (_convId: string, id: string) => {
    await new Promise<void>((resolve) => pending.push(resolve));
    return { id, content: id, files: [], forceTools: [], anonymousMode: false };
  }),
}));
vi.mock('@/core/messaging', () => ({
  dispatchSend: vi.fn(() => Promise.resolve()),
  sendUiMessage: vi.fn(),
}));
vi.mock('@/core/stream-send', () => ({ sendStreamingMessage: vi.fn() }));
vi.mock('@/core/batch-send', () => ({ sendBatchMessage: vi.fn() }));
vi.mock('@/components/Toast', () => ({
  toast: { info: vi.fn(), error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}));
vi.mock('@/components/messages', () => ({
  hideLoadingIndicator: vi.fn(),
  removeRenderedMessagesFrom: vi.fn(),
}));

import { resendOutboxEntry } from '@/core/rerun';
import { dispatchSend } from '@/core/messaging';

/** A stand-in for the browser's Web Locks: one holder per name, across "tabs". */
function fakeLocks(held: Set<string>): void {
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: async (
        name: string,
        _opts: { ifAvailable: boolean },
        cb: (lock: object | null) => Promise<void>
      ) => {
        if (held.has(name)) return cb(null);
        held.add(name);
        try {
          return await cb({ name });
        } finally {
          held.delete(name);
        }
      },
    },
  });
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

describe('overlapping resends of one failed message', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pending.length = 0;
    Reflect.deleteProperty(navigator, 'locks');
  });

  it('a second resend while the first restores its attachments does nothing', async () => {
    const first = resendOutboxEntry('c1', 'm1');
    await settle();
    const second = resendOutboxEntry('c1', 'm1');
    await settle();
    releaseRestore();
    await Promise.all([first, second]);

    expect(dispatchSend).toHaveBeenCalledTimes(1);
  });

  it('another tab holding the message lock means this tab leaves it alone', async () => {
    fakeLocks(new Set(['outbox-send:m1']));
    await resendOutboxEntry('c1', 'm1');

    expect(dispatchSend).not.toHaveBeenCalled();
  });

  it('the lock is released once the send settled', async () => {
    const held = new Set<string>();
    fakeLocks(held);
    const first = resendOutboxEntry('c1', 'm1');
    await settle();
    expect(held.has('outbox-send:m1')).toBe(true);
    releaseRestore();
    await first;

    expect(held.size).toBe(0);
    expect(dispatchSend).toHaveBeenCalledTimes(1);
  });

  it('once the first resend settled, a later one goes', async () => {
    const first = resendOutboxEntry('c1', 'm1');
    await settle();
    releaseRestore();
    await first;
    const second = resendOutboxEntry('c1', 'm1');
    await settle();
    releaseRestore();
    await second;

    expect(dispatchSend).toHaveBeenCalledTimes(2);
  });
});
