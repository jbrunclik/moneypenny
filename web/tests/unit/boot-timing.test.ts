/**
 * Startup reports its timing once, when ready (Nov 16 2026).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const report = vi.fn((_body: unknown) => Promise.resolve());
vi.mock('@/api/client-timing', () => ({ clientTiming: { report: (b: unknown) => report(b) } }));

const { markBootStage, reportBootTiming, routeLabel, _resetBootTiming } = await import(
  '@/core/startup/boot-timing'
);

const route = {
  conversationId: 'c1',
  isPlanner: false,
  isAgents: false,
  isStorage: false,
  isSports: false,
  isLanguage: false,
  isArchive: false,
  isTrash: false,
} as never;

beforeEach(() => {
  _resetBootTiming();
  report.mockClear();
  // jsdom has no matchMedia: a home-screen app
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: () => ({ matches: true }) as MediaQueryList,
  });
});

describe('reportBootTiming', () => {
  it('sends one report with integer marks, device and route', () => {
    vi.spyOn(performance, 'now').mockReturnValue(123.6);
    markBootStage('script');
    markBootStage('auth');
    markBootStage('auth'); // only the first time counts
    reportBootTiming(route);
    reportBootTiming(route);
    expect(report).toHaveBeenCalledTimes(1);
    const body = report.mock.calls[0]?.[0] as unknown as Record<string, unknown> & {
      marks: Record<string, number | null>;
    };
    expect(body.marks.script_ms).toBe(124);
    expect(body.marks.auth_ms).toBe(124);
    expect(body.marks.ready_ms).toBe(124);
    expect(body.marks.data_ms).toBeNull();
    expect(body.standalone).toBe(true);
    expect(['mobile', 'desktop']).toContain(body.viewport);
    expect(body.route).toBe('conversation');
  });

  it('a load that went to the background before it was ready says so', () => {
    markBootStage('auth');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    reportBootTiming(route);
    expect((report.mock.calls[0]?.[0] as { hidden: boolean }).hidden).toBe(true);
  });

  it('a load that stayed in view is not flagged', () => {
    markBootStage('auth');
    reportBootTiming(route);
    expect((report.mock.calls[0]?.[0] as { hidden: boolean }).hidden).toBe(false);
  });

  it('sends nothing for a load that was not signed in at boot', () => {
    markBootStage('script');
    reportBootTiming(route);
    expect(report).not.toHaveBeenCalled();
  });

  it('a failing report is dropped quietly', async () => {
    report.mockReturnValueOnce(Promise.reject(new Error('offline')));
    markBootStage('auth');
    expect(() => reportBootTiming(null)).not.toThrow();
    await Promise.resolve();
  });

  it('labels routes', () => {
    expect(routeLabel(null)).toBe('home');
    expect(routeLabel({ ...(route as object), conversationId: null, isPlanner: true } as never)).toBe(
      'planner'
    );
  });
});
