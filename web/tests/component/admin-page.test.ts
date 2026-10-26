import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminOverview } from '@/types/api';
import { renderAdminOverview, openAdminPage, closeAdminPage } from '@/components/AdminPage';
import { admin } from '@/api/admin';

function at<T>(items: ArrayLike<T>, i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item at index ${i}`);
  return item;
}

const money = (usd: number) => ({ usd, formatted: `${(usd * 23).toFixed(2)} Kč` });

type LayoutCheck = AdminOverview['layout_checks'][number];

function layoutCheck(overrides: Partial<LayoutCheck> = {}): LayoutCheck {
  return {
    app_version: 'abc123',
    build_marker: 'kb20',
    invariant: 'composer_gap',
    shape: 'overlap',
    count: 1,
    users: 1,
    standalone_count: 1,
    last_seen: '2026-10-25T13:10:00',
    ios_version: '26.0',
    measurements: { vv_height: 471, keyboard_inset: 391, deviation: -24 },
    ...overrides,
  };
}

function overview(overrides: Partial<AdminOverview> = {}): AdminOverview {
  return {
    generated_at: '2026-10-25T15:00:00',
    currency: 'CZK',
    spend: {
      today: money(12.5),
      month: money(80),
      threshold: money(10),
      users: [
        { name: 'Jana', today: money(12), month: money(50), month_chats: 31, month_turns: 412, over_threshold: true },
        { name: '<b>Petr</b>', today: money(0.5), month: money(30), month_chats: 8, month_turns: 95, over_threshold: false },
      ],
      daily: Array.from({ length: 30 }, (_, i) => ({
        date: `2026-09-${String(26 + i).padStart(2, '0')}`,
        amount: money(i === 29 ? 12.5 : 2),
      })),
      by_feature: [{ name: 'chat', amount: money(60) }, { name: 'agents', amount: money(20) }],
      by_model: [{ name: 'gemini-3.8-flash', amount: money(80) }],
    },
    agents: {
      runs_7d: 14,
      failed_7d: 2,
      pending_approvals: 1,
      recent_failures: [
        { agent_name: 'Briefing', user_name: 'Jana', started_at: '2026-10-25T07:00:00', error: 'Timeout <x>' },
      ],
    },
    search: {
      degraded_today: true,
      providers: [
        { provider: 'brave', configured: true, used: 1000, quota: 1000, available: false },
        { provider: 'ddgs', configured: true, used: 0, quota: null, available: true },
      ],
    },
    quality: { turns_7d: 300, median_ms: 9000, p95_ms: 45000, tool_error_rate: 0.03 },
    system: {
      version: 'abc123',
      database_bytes: 258785280,
      files_bytes: 516935680,
      last_backup_at: '2026-10-25T02:26:00',
      latest_migration: '0068_unique_planner_conversation',
      users: 5,
    },
    browser_errors: [
      {
        kind: 'unhandled_rejection',
        message: 'TypeError: <img> is undefined',
        stack: 'TypeError: x\n    at renderList (main.js:2:5)',
        path: '#/chat/abc',
        app_version: 'abc123',
        count: 7,
        users: 2,
        last_seen: '2026-10-25T14:02:00',
      },
    ],
    layout_checks: [
      layoutCheck({ app_version: 'abc123', build_marker: 'kb20', count: 4, standalone_count: 3 }),
      layoutCheck({ app_version: 'abc123', build_marker: 'kb20', invariant: 'stranded_pan', shape: 'keyboard-open', count: 1, standalone_count: 1 }),
      layoutCheck({ app_version: 'old999', build_marker: 'kb19', count: 9, users: 2, standalone_count: 0 }),
    ],
    ...overrides,
  };
}

function render(data: AdminOverview): HTMLElement {
  const div = document.createElement('div');
  div.append(...renderAdminOverview(data));
  return div;
}

describe('renderAdminOverview', () => {
  it('shows the family totals and a row per person', () => {
    const page = render(overview());
    expect(page.querySelector('.admin-spend-today')?.textContent).toContain('287.50 Kč');
    expect(page.querySelectorAll('.admin-user-row')).toHaveLength(2);
  });

  it('shows how many chats and turns each person had this month', () => {
    const cells = [...at(render(overview()).querySelectorAll('.admin-user-row'), 0).querySelectorAll('td')];
    expect(cells.map((c) => c.textContent)).toEqual(['Jana', expect.any(String), expect.any(String), '31', '412']);
  });

  it('highlights a person past the daily threshold', () => {
    const rows = render(overview()).querySelectorAll('.admin-user-row');
    expect(rows[0]?.classList.contains('admin-over-threshold')).toBe(true);
    expect(rows[1]?.classList.contains('admin-over-threshold')).toBe(false);
  });

  it('escapes names and error messages', () => {
    const page = render(overview());
    expect(page.querySelector('b')).toBeNull();
    expect(page.textContent).toContain('<b>Petr</b>');
    expect(page.textContent).toContain('Timeout <x>');
  });

  it('draws one bar per day, scaled to the busiest day', () => {
    const bars = render(overview()).querySelectorAll('.admin-chart rect');
    expect(bars).toHaveLength(30);
    const heights = Array.from(bars, (bar) => Number(bar.getAttribute('height')));
    expect(Math.max(...heights)).toBe(heights[29]);
  });

  it('copes with a month without spend', () => {
    const empty = overview();
    empty.spend.daily = empty.spend.daily.map((d) => ({ ...d, amount: money(0) }));
    const heights = Array.from(render(empty).querySelectorAll('.admin-chart rect'), (bar) =>
      bar.getAttribute('height')
    );
    expect(heights.every((h) => h === '0')).toBe(true);
  });

  it('flags exhausted search providers and the fallback', () => {
    const page = render(overview());
    expect(page.querySelector('.admin-search-degraded')).not.toBeNull();
    expect(page.querySelector('[data-provider="brave"]')?.textContent).toContain('1000 / 1000');
    expect(page.querySelector('[data-provider="ddgs"]')?.textContent).toContain('unmetered');
  });

  it('lists browser errors with how often, for how many and where', () => {
    const item = render(overview()).querySelector('.admin-browser-errors li');
    expect(item?.textContent).toContain('TypeError: <img> is undefined'); // escaped, as text
    expect(item?.querySelector('img')).toBeNull();
    expect(item?.textContent).toContain('7×');
    expect(item?.textContent).toContain('2 people');
    expect(item?.textContent).toContain('#/chat/abc');
    expect(item?.querySelector('details pre')?.textContent).toContain('renderList');
  });

  it('says when the browser reported no errors', () => {
    const page = render(overview({ browser_errors: [] }));
    expect(page.textContent).toContain('No browser errors in the last 7 days');
  });

  it('groups layout checks by build, the deployed one first and marked', () => {
    const builds = [...render(overview()).querySelectorAll('.admin-layout-build')];
    expect(builds.map((b) => b.querySelector('h3 span')?.textContent)).toEqual(['abc123 · kb20', 'old999 · kb19']);
    expect(at(builds, 0).querySelector('.admin-layout-current')?.textContent).toBe('Deployed');
    expect(at(builds, 1).querySelector('.admin-layout-current')).toBeNull();
    expect(at(builds, 0).querySelector('.admin-layout-total')?.textContent).toBe('5×');
    expect(at(builds, 0).querySelectorAll('li')).toHaveLength(2);
  });

  it('says what failed, how often, where and the latest numbers', () => {
    const [deployed, old] = [...render(overview()).querySelectorAll('.admin-layout-checks li')].filter(
      (li) => li.getAttribute('data-invariant') === 'composer_gap'
    );
    expect(deployed?.textContent).toContain('Composer off the keyboard');
    expect(deployed?.textContent).toContain('covered by it');
    expect(deployed?.textContent).toContain('4×');
    expect(deployed?.textContent).toContain('3 in the app, 1 in a tab');
    expect(deployed?.textContent).toContain('iOS 26.0');
    expect(deployed?.querySelector('details pre')?.textContent).toContain('keyboard_inset 391');
    expect(old?.textContent).toContain('2 people');
    expect(old?.textContent).toContain('browser tab');
  });

  it('escapes an unknown check and says when none failed', () => {
    const unknown = render(overview({ layout_checks: [layoutCheck({ invariant: '<i>new</i>', shape: '<b>x</b>' })] }));
    expect(unknown.querySelector('.admin-layout-checks i, .admin-layout-checks b')).toBeNull();
    expect(unknown.querySelector('.admin-layout-name')?.textContent).toBe('<i>new</i>');
    const none = render(overview({ layout_checks: [] }));
    expect(none.textContent).toContain('No layout check failed in the last 7 days');
  });

  it('shows response quality and system facts readably', () => {
    const text = render(overview()).textContent ?? '';
    expect(text).toContain('9.0 s');
    expect(text).toContain('3.0%');
    expect(text).toContain('247 MB');
    expect(text).toContain('0068_unique_planner_conversation');
  });
});

describe('openAdminPage', () => {
  afterEach(() => {
    closeAdminPage();
    vi.restoreAllMocks();
  });

  it('opens a full-screen page, loads the overview and closes on Escape', async () => {
    vi.spyOn(admin, 'getOverview').mockResolvedValue(overview());
    await openAdminPage();
    const page = document.querySelector('.admin-page');
    expect(page?.getAttribute('aria-modal')).toBe('true');
    expect(page?.querySelector('.admin-user-row')).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.querySelector('.admin-page')).toBeNull();
  });

  it('offers the device checks: the page closes, then the run starts', async () => {
    vi.spyOn(admin, 'getOverview').mockResolvedValue(overview());
    vi.spyOn(admin, 'listDeviceCheckRuns').mockResolvedValue([]);
    const onRunDeviceChecks = vi.fn(() => {
      expect(document.querySelector('.admin-page')).toBeNull();
    });
    await openAdminPage({ onRunDeviceChecks });
    const section = document.querySelector('.admin-page .device-check-section');
    expect(section?.querySelector('h2')?.textContent).toBe('Device checks');
    // Before the closing "Updated" note
    expect(section?.nextElementSibling?.textContent).toContain('Updated');
    section?.querySelector<HTMLButtonElement>('.device-check-run-btn')?.click();
    expect(onRunDeviceChecks).toHaveBeenCalledOnce();
  });

  it('has no device checks section without a runner', async () => {
    vi.spyOn(admin, 'getOverview').mockResolvedValue(overview());
    await openAdminPage();
    expect(document.querySelector('.device-check-section')).toBeNull();
  });

  it('shows an error state when the overview fails to load', async () => {
    vi.spyOn(admin, 'getOverview').mockRejectedValue(new Error('403'));
    await openAdminPage();
    expect(document.querySelector('.admin-page .admin-error')).not.toBeNull();
  });
});
