/**
 * Unit tests for Toast notification component
 *
 * These tests focus on:
 * 1. Store integration (notification state management)
 * 2. Toast behavior (duration, actions, auto-dismiss)
 * 3. Convenience functions
 *
 * Note: Tests use vi.resetModules() to get fresh Toast instances since the
 * component uses module-level state (toastContainer, toastTimeouts).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useStore } from '@/state/store';

// Helper to reset store state
function resetStore() {
  useStore.setState({
    notifications: [],
    token: null,
    user: null,
    googleClientId: null,
    conversations: [],
    currentConversation: null,
    models: [],
    defaultModel: 'gemini-3-flash-preview',
    isLoading: false,
    isSidebarOpen: false,
    streamingEnabled: true,
    forceTools: [],
    pendingFiles: [],
    uploadConfig: {
      maxFileSize: 20 * 1024 * 1024,
      maxVideoFileSize: 100 * 1024 * 1024,
      maxFilesPerMessage: 10,
      allowedFileTypes: [],
    },
    appVersion: null,
    newVersionAvailable: false,
    versionBannerDismissed: false,
  });
}

// Reset DOM and modules before each test
function resetAll() {
  document.body.innerHTML = '';
  vi.resetModules();
}

describe('Toast - Store Integration', () => {
  beforeEach(() => {
    resetStore();
  });

  describe('addNotification', () => {
    it('adds notification to store', () => {
      useStore.getState().addNotification({
        id: 'toast-1',
        type: 'success',
        message: 'Test message',
        duration: 5000,
      });

      const notifications = useStore.getState().notifications;
      expect(notifications).toHaveLength(1);
      expect(notifications[0]).toEqual({
        id: 'toast-1',
        type: 'success',
        message: 'Test message',
        duration: 5000,
      });
    });

    it('adds multiple notifications', () => {
      useStore.getState().addNotification({
        id: 'toast-1',
        type: 'success',
        message: 'First',
        duration: 5000,
      });
      useStore.getState().addNotification({
        id: 'toast-2',
        type: 'error',
        message: 'Second',
        duration: 0,
      });

      expect(useStore.getState().notifications).toHaveLength(2);
    });

    it('preserves action callback', () => {
      const mockCallback = vi.fn();
      useStore.getState().addNotification({
        id: 'toast-1',
        type: 'error',
        message: 'Error with retry',
        action: { label: 'Retry', onClick: mockCallback },
        duration: 0,
      });

      const notification = useStore.getState().notifications[0];
      expect(notification.action).toBeDefined();
      expect(notification.action?.label).toBe('Retry');

      notification.action?.onClick();
      expect(mockCallback).toHaveBeenCalled();
    });
  });

  describe('dismissNotification', () => {
    it('removes notification by id', () => {
      useStore.getState().addNotification({
        id: 'toast-1',
        type: 'success',
        message: 'Test',
        duration: 5000,
      });
      useStore.getState().addNotification({
        id: 'toast-2',
        type: 'error',
        message: 'Error',
        duration: 0,
      });

      useStore.getState().dismissNotification('toast-1');

      const notifications = useStore.getState().notifications;
      expect(notifications).toHaveLength(1);
      expect(notifications[0].id).toBe('toast-2');
    });

    it('handles non-existent id gracefully', () => {
      useStore.getState().addNotification({
        id: 'toast-1',
        type: 'success',
        message: 'Test',
        duration: 5000,
      });

      // Should not throw
      useStore.getState().dismissNotification('non-existent');

      expect(useStore.getState().notifications).toHaveLength(1);
    });
  });
});

describe('Toast - Component', () => {
  beforeEach(() => {
    resetStore();
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('creates toast container element on init', async () => {
    const { initToast } = await import('@/components/Toast');
    initToast();

    const container = document.getElementById('toast-container');
    expect(container).not.toBeNull();
    expect(container?.classList.contains('toast-container')).toBe(true);
  });

  it('showToast adds notification to store', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    showToast({ type: 'success', message: 'Success!' });

    expect(store.getState().notifications).toHaveLength(1);
    expect(store.getState().notifications[0].type).toBe('success');
    expect(store.getState().notifications[0].message).toBe('Success!');
  });

  it('showToast returns unique id', async () => {
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    const id1 = showToast({ type: 'info', message: 'First' });
    const id2 = showToast({ type: 'info', message: 'Second' });

    expect(typeof id1).toBe('string');
    expect(id1.startsWith('toast-')).toBe(true);
    expect(id1).not.toBe(id2);
  });

  it('uses default duration for non-action toasts', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    showToast({ type: 'success', message: 'Success!' });

    // Default duration is 5000ms
    expect(store.getState().notifications[0].duration).toBe(5000);
  });

  it('uses persistent duration (0) for toasts with actions', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    showToast({
      type: 'error',
      message: 'Error',
      action: { label: 'Retry', onClick: () => {} },
    });

    // Should be persistent (0) when action is present
    expect(store.getState().notifications[0].duration).toBe(0);
  });

  it('allows custom duration override', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    showToast({ type: 'info', message: 'Custom', duration: 10000 });

    expect(store.getState().notifications[0].duration).toBe(10000);
  });

  it('auto-dismisses after duration', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    showToast({ type: 'success', message: 'Auto dismiss', duration: 3000 });

    expect(store.getState().notifications).toHaveLength(1);

    // Advance past duration
    vi.advanceTimersByTime(3000);

    // After animation delay (200ms)
    vi.advanceTimersByTime(200);

    expect(store.getState().notifications).toHaveLength(0);
  });

  it('does not auto-dismiss persistent toasts', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast } = await import('@/components/Toast');
    initToast();

    showToast({ type: 'error', message: 'Persistent', duration: 0 });

    // Advance a long time
    vi.advanceTimersByTime(60000);

    // Should still be present
    expect(store.getState().notifications).toHaveLength(1);
  });

  it('dismissAllToasts clears all notifications', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, showToast, dismissAllToasts } = await import('@/components/Toast');
    initToast();

    showToast({ type: 'success', message: 'First', duration: 0 });
    showToast({ type: 'error', message: 'Second', duration: 0 });
    showToast({ type: 'info', message: 'Third', duration: 0 });

    expect(store.getState().notifications).toHaveLength(3);

    dismissAllToasts();

    // After animation (200ms)
    vi.advanceTimersByTime(200);

    expect(store.getState().notifications).toHaveLength(0);
  });
});

describe('Toast - Convenience Functions', () => {
  beforeEach(() => {
    resetStore();
    resetAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('toast.success creates success notification', async () => {
    // Re-import store after resetModules to get fresh reference
    const { useStore: store } = await import('@/state/store');
    const { initToast, toast } = await import('@/components/Toast');
    initToast();

    toast.success('Great!');

    expect(store.getState().notifications[0].type).toBe('success');
  });

  it('toast.error creates error notification', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, toast } = await import('@/components/Toast');
    initToast();

    toast.error('Bad!');

    expect(store.getState().notifications[0].type).toBe('error');
  });

  it('toast.warning creates warning notification', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, toast } = await import('@/components/Toast');
    initToast();

    toast.warning('Careful!');

    expect(store.getState().notifications[0].type).toBe('warning');
  });

  it('toast.info creates info notification', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, toast } = await import('@/components/Toast');
    initToast();

    toast.info('FYI');

    expect(store.getState().notifications[0].type).toBe('info');
  });

  it('toast.error supports action option', async () => {
    const { useStore: store } = await import('@/state/store');
    const { initToast, toast } = await import('@/components/Toast');
    initToast();

    const mockRetry = vi.fn();
    toast.error('Failed', { action: { label: 'Retry', onClick: mockRetry } });

    const notification = store.getState().notifications[0];
    expect(notification.action?.label).toBe('Retry');
  });
});
