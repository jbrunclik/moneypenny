/**
 * Unit tests for the offline/online banner.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { initConnectivity } from '@/core/connectivity';
import { useStore } from '@/state/store';

function setOnLine(value: boolean): void {
  Object.defineProperty(navigator, 'onLine', { value, configurable: true });
}

describe('connectivity banner', () => {
  beforeEach(() => {
    useStore.setState({ notifications: [] });
    setOnLine(true);
    initConnectivity();
  });

  it('shows a persistent warning when the connection drops', () => {
    window.dispatchEvent(new Event('offline'));
    const notifications = useStore.getState().notifications;
    expect(notifications.some((n) => n.type === 'warning' && n.duration === 0)).toBe(true);
  });

  it('clears the warning and confirms when back online', () => {
    window.dispatchEvent(new Event('offline'));
    window.dispatchEvent(new Event('online'));
    const notifications = useStore.getState().notifications;
    expect(notifications.some((n) => n.type === 'warning')).toBe(false);
    expect(notifications.some((n) => n.type === 'success')).toBe(true);
  });

  it('does not stack duplicate offline warnings', () => {
    window.dispatchEvent(new Event('offline'));
    window.dispatchEvent(new Event('offline'));
    const warnings = useStore.getState().notifications.filter((n) => n.type === 'warning');
    expect(warnings).toHaveLength(1);
  });
});
