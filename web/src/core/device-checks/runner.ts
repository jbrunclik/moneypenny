/**
 * The guided device check run (admin page -> Run device checks): open a
 * throwaway fixture conversation through the real path, run the scenario
 * registry, store the results, and put everything back. See
 * docs/superpowers/specs/2026-10-26-device-check-runner-design.md.
 */
import { admin } from '../../api/admin';
import { hideLoadingIndicator } from '../../components/messages';
import {
  openDeviceCheckRunner,
  type DeviceCheckRunnerView,
  type DeviceCheckSummary,
} from '../../components/DeviceCheckRunner';
import { useStore } from '../../state/store';
import type { DeviceCheckRunRequest, DeviceCheckScenarioResult } from '../../types/api';
import { isTempConversation } from '../../utils/conversation-id';
import { getElementById } from '../../utils/dom';
import { createLogger } from '../../utils/logger';
import { KEYBOARD_BUILD_MARKER } from '../../config';
import { createConversation, selectConversation } from '../conversation';
import { summarizeUserAgent } from './evaluate';
import { DeviceCheckAbortedError } from './measure';
import {
  captureEnvironment,
  DEVICE_CHECK_SCENARIOS,
  hasSoftwareKeyboard,
  skipReason,
  type DeviceCheckContext,
  type DeviceCheckScenario,
} from './scenarios';

const log = createLogger('core/device-checks/runner');

// The run in progress: a second tap on Run while one runs is ignored
let running: AbortController | null = null;

/** Tally results the way the server does (an error counts as failed). */
export function summarize(results: readonly DeviceCheckScenarioResult[]): DeviceCheckSummary {
  return {
    passed: results.filter((r) => r.status === 'passed').length,
    failed: results.filter((r) => r.status === 'failed' || r.status === 'error').length,
    skipped: results.filter((r) => r.status === 'skipped').length,
  };
}

async function runScenario(
  scenario: DeviceCheckScenario,
  ctx: DeviceCheckContext,
  softwareKeyboard: boolean
): Promise<DeviceCheckScenarioResult> {
  const base = { id: scenario.id, title: scenario.title };
  const skip = skipReason(scenario.requires, softwareKeyboard, ctx.shared.keyboardShown);
  if (skip !== null) {
    return { ...base, status: 'skipped', duration_ms: 0, measurements: {}, notes: [skip] };
  }
  const started = performance.now();
  try {
    const outcome = await scenario.run(ctx);
    return { ...base, ...outcome, duration_ms: Math.round(performance.now() - started) };
  } catch (error) {
    if (ctx.signal.aborted) throw new DeviceCheckAbortedError();
    log.error('Device check scenario threw', { error, scenario: scenario.id });
    const message = error instanceof Error ? error.message : String(error);
    return {
      ...base,
      status: 'error',
      duration_ms: Math.round(performance.now() - started),
      measurements: {},
      notes: [message.slice(0, 300)],
    };
  }
}

async function runAll(
  view: DeviceCheckRunnerView,
  container: HTMLElement,
  signal: AbortSignal
): Promise<DeviceCheckScenarioResult[]> {
  const softwareKeyboard = hasSoftwareKeyboard();
  const ctx: DeviceCheckContext = {
    container,
    signal,
    askTap: (label, onTap) => view.askTap(label, onTap, signal),
    shared: { turnEl: null, keyboardShown: false },
  };
  const results: DeviceCheckScenarioResult[] = [];
  for (const scenario of DEVICE_CHECK_SCENARIOS) {
    if (signal.aborted) throw new DeviceCheckAbortedError();
    view.setStatus(scenario.id, 'running');
    const result = await runScenario(scenario, ctx, softwareKeyboard);
    results.push(result);
    view.setStatus(scenario.id, result.status, result.notes?.[0]);
  }
  return results;
}

/** Leave the fixture: back to where the user was, then delete it for good. */
async function restore(previousId: string | null, fixtureId: string | null): Promise<void> {
  document.getElementById('message-input')?.blur();
  hideLoadingIndicator();
  if (fixtureId !== null) {
    if (previousId !== null && previousId !== fixtureId && !isTempConversation(previousId)) {
      await selectConversation(previousId);
    } else {
      createConversation();
    }
    const store = useStore.getState();
    if (store.conversations.some((c) => c.id === fixtureId)) store.removeConversation(fixtureId);
  }
  try {
    await admin.deleteDeviceCheckFixture();
  } catch (error) {
    // The next run purges it before creating its own
    log.warn('Failed to delete the device check fixture', { error });
  }
}

function buildRun(results: DeviceCheckScenarioResult[], startedAt: string): DeviceCheckRunRequest {
  const environment = results.find((r) => r.id === 'environment')?.measurements ?? captureEnvironment();
  const appVersion = document.getElementById('app')?.dataset.version;
  return {
    build_marker: KEYBOARD_BUILD_MARKER,
    ...(appVersion !== undefined && { app_version: appVersion }),
    standalone: environment.standalone === true,
    ua_summary: summarizeUserAgent(navigator.userAgent, navigator.platform, navigator.maxTouchPoints),
    environment,
    scenarios: results,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
  };
}

async function runSuite(view: DeviceCheckRunnerView, signal: AbortSignal): Promise<DeviceCheckSummary> {
  const previousId = useStore.getState().currentConversation?.id ?? null;
  const startedAt = new Date().toISOString();
  let fixtureId: string | null = null;
  let results: DeviceCheckScenarioResult[];
  try {
    const fixture = await admin.createDeviceCheckFixture();
    fixtureId = fixture.conversation_id;
    await selectConversation(fixture.conversation_id);
    const container = getElementById<HTMLDivElement>('messages');
    if (!container || useStore.getState().currentConversation?.id !== fixtureId) {
      throw new Error('The fixture conversation did not open');
    }
    results = await runAll(view, container, signal);
  } finally {
    await restore(previousId, fixtureId);
  }
  const summary = summarize(results);
  try {
    await admin.saveDeviceCheckRun(buildRun(results, startedAt));
  } catch (error) {
    log.error('Failed to save the device check run', { error });
    return { ...summary, problem: 'The run could not be saved.' };
  }
  return summary;
}

/** Run the suite; `onClose` runs when the summary is closed. */
export async function runDeviceChecks(options: { onClose: () => void }): Promise<void> {
  if (running) return;
  const controller = new AbortController();
  running = controller;
  const view = openDeviceCheckRunner(
    DEVICE_CHECK_SCENARIOS.map(({ id, title }) => ({ id, title })),
    { onStop: () => controller.abort(), onClose: options.onClose }
  );
  try {
    view.showSummary(await runSuite(view, controller.signal));
  } catch (error) {
    const stopped = controller.signal.aborted;
    if (!stopped) log.error('Device checks failed', { error });
    view.showSummary({
      passed: 0,
      failed: 0,
      skipped: 0,
      problem: stopped ? 'Stopped - nothing was saved.' : 'The run failed - nothing was saved.',
    });
  } finally {
    running = null;
  }
}
