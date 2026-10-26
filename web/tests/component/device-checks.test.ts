/**
 * The device check runner card and the admin page's history section.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { openDeviceCheckRunner } from '@/components/DeviceCheckRunner';
import { createDeviceChecksSection, renderDeviceCheckRuns, runResult, runTime } from '@/components/AdminDeviceChecks';
import { admin } from '@/api/admin';
import type { DeviceCheckRun } from '@/types/api';

const ROWS = [
  { id: 'environment', title: 'Environment' },
  { id: 'keyboard-open', title: 'Keyboard opens' },
];

function run(overrides: Partial<DeviceCheckRun> = {}): DeviceCheckRun {
  return {
    id: 'run-1',
    build_marker: 'kb19',
    app_version: 'abc1234',
    standalone: true,
    ua_summary: 'iOS 26.1 · WebKit',
    environment: { inner_height: 812 },
    scenarios: [
      {
        id: 'send-to-top',
        title: 'Send-to-top anchors the turn',
        status: 'failed',
        duration_ms: 1840,
        measurements: { anchor_offset_px: 9, anchored: true },
        notes: ['turn 9px below the anchor'],
      },
      { id: 'keyboard-open', title: '<b>Keyboard</b> opens', status: 'skipped', duration_ms: 0, measurements: {}, notes: [] },
    ],
    passed: 3,
    failed: 1,
    skipped: 2,
    started_at: '2026-10-26T13:30:00.000000+00:00',
    finished_at: '2026-10-26T13:32:00.000000+00:00',
    created_at: '2026-10-26T13:32:01.000000+00:00',
    ...overrides,
  };
}

describe('device check runner card', () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it('lists the scenarios and shows each status with its first note', () => {
    const view = openDeviceCheckRunner(ROWS, { onStop: vi.fn(), onClose: vi.fn() });
    view.setStatus('keyboard-open', 'skipped', 'no software keyboard');
    const row = document.querySelector('[data-check-id="keyboard-open"]');
    expect(row?.getAttribute('data-status')).toBe('skipped');
    expect(row?.textContent).toContain('Skipped');
    expect(row?.textContent).toContain('no software keyboard');
    expect(document.querySelector('.device-check-live')?.textContent).toBe('Keyboard opens: Skipped');
  });

  it('runs the tap action inside the click, then resolves', async () => {
    const view = openDeviceCheckRunner(ROWS, { onStop: vi.fn(), onClose: vi.fn() });
    const input = document.body.appendChild(document.createElement('textarea'));
    const asked = view.askTap('Tap to open the keyboard', () => input.focus(), new AbortController().signal);
    const button = document.querySelector<HTMLButtonElement>('.device-check-tap');
    expect(button?.textContent).toBe('Tap to open the keyboard');
    button?.click();
    // Focused synchronously by the click handler itself
    expect(document.activeElement).toBe(input);
    await expect(asked).resolves.toBeUndefined();
    expect(document.querySelector('.device-check-tap')).toBeNull();
  });

  it('rejects a pending tap when the run is stopped', async () => {
    const onStop = vi.fn();
    const view = openDeviceCheckRunner(ROWS, { onStop, onClose: vi.fn() });
    const controller = new AbortController();
    const asked = view.askTap('Tap', vi.fn(), controller.signal);
    document.querySelector<HTMLButtonElement>('.device-check-stop')?.click();
    expect(onStop).toHaveBeenCalledOnce();
    controller.abort();
    await expect(asked).rejects.toThrow('stopped');
    expect(document.querySelector('.device-check-prompt')?.classList.contains('hidden')).toBe(true);
  });

  it('ends with a summary whose Close hands back to the caller', () => {
    const onClose = vi.fn();
    const view = openDeviceCheckRunner(ROWS, { onStop: vi.fn(), onClose });
    view.showSummary({ passed: 3, failed: 0, skipped: 3 });
    expect(document.querySelector('.device-check-live')?.textContent).toBe('3/3 passed, 3 skipped');
    expect(document.querySelector('.device-check-stop')).toBeNull();
    document.querySelector<HTMLButtonElement>('.device-check-close')?.click();
    expect(onClose).toHaveBeenCalledOnce();
    expect(document.querySelector('.device-check-card')).toBeNull();
  });

  it('marks a summary with failures or a problem', () => {
    const view = openDeviceCheckRunner(ROWS, { onStop: vi.fn(), onClose: vi.fn() });
    view.showSummary({ passed: 0, failed: 0, skipped: 0, problem: 'Stopped - nothing was saved.' });
    const card = document.querySelector('.device-check-card');
    expect(card?.classList.contains('device-check-has-failures')).toBe(true);
    expect(card?.textContent).toContain('Stopped - nothing was saved.');
  });
});

describe('device check history', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it('formats the result and the time', () => {
    expect(runResult({ passed: 6, failed: 0, skipped: 0 })).toBe('6/6 passed');
    expect(runResult({ passed: 3, failed: 1, skipped: 2 })).toBe('3/4 passed, 2 skipped');
    const now = new Date(2026, 9, 26, 18, 0);
    expect(runTime(new Date(2026, 9, 26, 14, 32).toISOString(), now)).toBe('today 14:32');
    expect(runTime(new Date(2026, 9, 25, 9, 5).toISOString(), now)).toBe('yesterday 09:05');
    expect(runTime(new Date(2026, 9, 20, 8, 0).toISOString(), now)).toBe('Oct 20 08:00');
  });

  it('shows one summary line per run and every scenario with its numbers', () => {
    const list = renderDeviceCheckRuns([run(), run({ id: 'run-2', build_marker: 'kb18', failed: 0, standalone: false })]);
    const summaries = [...list.querySelectorAll('summary')].map((s) => s.textContent);
    expect(summaries[0]).toContain('[kb19]');
    expect(summaries[0]).toContain('3/4 passed, 2 skipped');
    expect(summaries[0]).toContain('standalone · iOS 26.1 · WebKit');
    expect(summaries[1]).toContain('browser tab');
    expect(list.querySelector('.device-check-run')?.getAttribute('data-status')).toBe('failed');
    const scenario = list.querySelector('.device-check-scenario');
    expect(scenario?.textContent).toContain('turn 9px below the anchor');
    expect(scenario?.textContent).toContain('anchor_offset_px');
    expect(scenario?.textContent).toContain('1.8 s');
    // Text, never markup
    expect(list.querySelector('b')).toBeNull();
    expect(list.textContent).toContain('<b>Keyboard</b> opens');
  });

  it('says when there are no runs yet', () => {
    expect(renderDeviceCheckRuns([]).textContent).toContain('No runs yet');
  });

  it('loads the history and runs the checks from its button', async () => {
    vi.spyOn(admin, 'listDeviceCheckRuns').mockResolvedValue([run()]);
    const onRun = vi.fn();
    const section = document.body.appendChild(createDeviceChecksSection(onRun));
    await vi.waitFor(() => expect(section.querySelector('.device-check-run')).not.toBeNull());
    section.querySelector<HTMLButtonElement>('.device-check-run-btn')?.click();
    expect(onRun).toHaveBeenCalledOnce();
  });

  it('shows an error when the history fails to load', async () => {
    vi.spyOn(admin, 'listDeviceCheckRuns').mockRejectedValue(new Error('500'));
    const section = createDeviceChecksSection(vi.fn());
    await vi.waitFor(() => expect(section.querySelector('.admin-error')).not.toBeNull());
  });
});
