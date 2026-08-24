/**
 * Unit tests for the push-receipt sync nudge: when the service worker
 * relays that a push arrived, open app windows must sync immediately
 * instead of waiting for the next poll tick.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';

const incrementalSync = vi.fn();

vi.mock('@/sync/SyncManager', () => ({
  getSyncManager: () => ({ incrementalSync }),
}));

vi.mock('@/core/sync-banner', () => ({
  reloadCurrentConversation: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  push: {},
}));

vi.mock('@/utils/logger', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

import { registerServiceWorker } from '@/core/push';

type MessageHandler = (event: { data: unknown }) => void;

describe('push-received sync nudge', () => {
  // The worker message listener installs once per module load, so the
  // handler is captured once for all tests in this file
  let messageHandler: MessageHandler | null = null;

  beforeAll(async () => {
    // Minimal service worker environment for isSupported() + register()
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        register: vi.fn().mockResolvedValue({ scope: '/' }),
        addEventListener: vi.fn((type: string, handler: MessageHandler) => {
          if (type === 'message') messageHandler = handler;
        }),
      },
    });
    vi.stubGlobal('PushManager', class {});
    vi.stubGlobal('Notification', class {});

    await registerServiceWorker();
  });

  beforeEach(() => {
    incrementalSync.mockClear();
  });

  it('triggers an incremental sync when the SW reports a received push', () => {
    expect(messageHandler).not.toBeNull();

    messageHandler!({ data: { type: 'push-received' } });

    expect(incrementalSync).toHaveBeenCalledTimes(1);
  });

  it('ignores unrelated worker messages', () => {
    messageHandler!({ data: { type: 'something-else' } });
    messageHandler!({ data: null });

    expect(incrementalSync).not.toHaveBeenCalled();
  });
});
