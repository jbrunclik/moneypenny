/**
 * The admin page's "Device checks" section: the run button and the run
 * history (one row per run, newest first, expandable to every scenario's
 * numbers). The run itself is core/device-checks/runner.ts, reached through
 * the `onRun` callback (components don't import core).
 */
import { admin } from '../api/admin';
import type { DeviceCheckRun } from '../types/api';
import { createElement } from '../utils/dom';
import { createLogger } from '../utils/logger';

const log = createLogger('components/AdminDeviceChecks');

type Scenario = DeviceCheckRun['scenarios'][number];

const STATUS_LABELS: Record<Scenario['status'], string> = {
  passed: 'Passed',
  failed: 'Failed',
  skipped: 'Skipped',
  error: 'Error',
};

const MS_PER_DAY = 86_400_000;
const pad = (n: number): string => String(n).padStart(2, '0');

/** "today 14:32", "yesterday 09:05", "Oct 24 18:00" (local time). */
export function runTime(iso: string, now = new Date()): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const clock = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  const day = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(at)) / MS_PER_DAY);
  if (days === 0) return `today ${clock}`;
  if (days === 1) return `yesterday ${clock}`;
  return `${at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${clock}`;
}

/** "3/3 passed, 3 skipped" */
export function runResult(run: Pick<DeviceCheckRun, 'passed' | 'failed' | 'skipped'>): string {
  const skipped = run.skipped ? `, ${run.skipped} skipped` : '';
  return `${run.passed}/${run.passed + run.failed} passed${skipped}`;
}

function measurementList(measurements: DeviceCheckRun['environment']): HTMLElement | null {
  const entries = Object.entries(measurements);
  if (!entries.length) return null;
  return createElement(
    'ul',
    { class: 'device-check-measurements' },
    entries.map(([key, value]) =>
      createElement('li', {}, [createElement('span', {}, [key]), createElement('code', {}, [String(value)])])
    )
  );
}

function scenarioItem(s: Scenario): HTMLLIElement {
  const item = createElement('li', { class: 'device-check-scenario', 'data-status': s.status }, [
    createElement('div', { class: 'device-check-scenario-head' }, [
      createElement('span', { class: 'device-check-scenario-title' }, [s.title]),
      createElement('span', { class: 'device-check-status' }, [STATUS_LABELS[s.status]]),
      createElement('span', { class: 'device-check-duration' }, [`${(s.duration_ms / 1000).toFixed(1)} s`]),
    ]),
    ...s.notes.map((note) => createElement('p', { class: 'device-check-note' }, [note])),
  ]);
  const list = measurementList(s.measurements);
  if (list) item.append(list);
  return item;
}

function runItem(run: DeviceCheckRun, now: Date): HTMLLIElement {
  const meta = [run.standalone ? 'standalone' : 'browser tab', run.ua_summary, runTime(run.created_at, now)];
  const details = createElement('details', {}, [
    createElement('summary', {}, [
      createElement('span', { class: 'device-check-run-marker' }, [run.build_marker ? `[${run.build_marker}]` : '[no marker]']),
      createElement('span', { class: 'device-check-run-result' }, [runResult(run)]),
      createElement('span', { class: 'device-check-run-meta' }, [meta.join(' · ')]),
    ]),
    createElement('ol', { class: 'device-check-scenarios' }, run.scenarios.map(scenarioItem)),
  ]);
  if (run.app_version) details.append(createElement('p', { class: 'admin-note' }, [`Build ${run.app_version}`]));
  return createElement('li', { class: 'device-check-run', 'data-status': run.failed > 0 ? 'failed' : 'passed' }, [details]);
}

/** The history: one expandable row per run, or a note when there are none. */
export function renderDeviceCheckRuns(runs: readonly DeviceCheckRun[], now = new Date()): HTMLElement {
  if (!runs.length) {
    return createElement('p', { class: 'admin-note' }, [
      'No runs yet. Run the checks on each device after a keyboard or scroll change.',
    ]);
  }
  return createElement('ul', { class: 'device-check-runs' }, runs.map((run) => runItem(run, now)));
}

/** The section element: run button, then the history once loaded. */
export function createDeviceChecksSection(onRun: () => void): HTMLElement {
  const run = createElement('button', { type: 'button', class: 'device-check-run-btn' }, ['Run device checks']);
  run.addEventListener('click', onRun);
  const history = createElement('div', { class: 'device-check-history' }, [
    createElement('p', { class: 'admin-loading' }, ['Loading…']),
  ]);
  const section = createElement('section', { class: 'admin-section device-check-section' }, [
    createElement('div', { class: 'device-check-section-head' }, [createElement('h2', {}, ['Device checks']), run]),
    createElement('p', { class: 'admin-note' }, [
      'Scripted layout checks run in this app on this device; the keyboard steps ask for taps. On the iPhone, run them from the installed app.',
    ]),
    history,
  ]);
  void admin
    .listDeviceCheckRuns()
    .then((runs) => history.replaceChildren(renderDeviceCheckRuns(runs)))
    .catch((error: unknown) => {
      log.error('Failed to load device check runs', { error });
      history.replaceChildren(
        createElement('p', { class: 'admin-error' }, ['The device check history could not be loaded.'])
      );
    });
  return section;
}
