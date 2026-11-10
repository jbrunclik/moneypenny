/**
 * Device checks that need the user's own gesture: iOS momentum scrolling
 * only follows a real flick, so these ask for one and measure whether the
 * one-shot scroll corrections made meanwhile landed (utils/scroll-writes.ts;
 * TODO "Scroll: iOS dropped writes" and "Artifact frame scroll stability").
 */
import { useStore } from '../../state/store';
import type { DeviceCheckMeasurements } from '../../types/api';
import {
  DEVICE_CHECK_ARTIFACT_SCROLL_MS,
  DEVICE_CHECK_FLICK_TIMEOUT_MS,
  LOAD_OLDER_MESSAGES_THRESHOLD_PX,
} from '../../config';
import { scrollWriteStats, type ScrollWriteSource, type ScrollWriteStats } from '../../utils/scroll-writes';
import { evaluateScrollWrites } from './evaluate';
import { waitForStable, waitUntil } from './measure';
import type { DeviceCheckContext, DeviceCheckScenario, ScenarioOutcome } from './scenarios';

const COUNTDOWN_TICK_MS = 1000;

/** The change in one source's counts between two snapshots. */
function delta(before: ScrollWriteStats, after: ScrollWriteStats): ScrollWriteStats {
  return {
    writes: after.writes - before.writes,
    verified: after.verified - before.verified,
    dropped: after.dropped - before.dropped,
    maxMissPx: after.maxMissPx,
    last: after.writes > before.writes ? after.last : null,
  };
}

function writeMeasurements(d: ScrollWriteStats): DeviceCheckMeasurements {
  return {
    writes: d.writes,
    verified: d.verified,
    dropped: d.dropped,
    max_miss_px: d.maxMissPx,
    last_from_px: d.last?.fromPx ?? null,
    last_target_px: d.last?.targetPx ?? null,
    last_actual_px: d.last?.actualPx ?? null,
  };
}

/** Judge the corrections one source made during the gesture. */
function judge(
  source: ScrollWriteSource,
  before: ScrollWriteStats,
  extra: DeviceCheckMeasurements,
  noWritesNote: string
): ScenarioOutcome {
  const d = delta(before, scrollWriteStats()[source]);
  const measurements = { ...writeMeasurements(d), ...extra };
  if (d.verified === 0) return { status: 'skipped', measurements, notes: [noWritesNote] };
  const verdict = evaluateScrollWrites(d);
  return { status: verdict.status, measurements, notes: verdict.failures };
}

async function settle(ctx: DeviceCheckContext): Promise<void> {
  await waitForStable(() => ctx.container.scrollHeight, ctx.signal);
  await waitForStable(() => ctx.container.scrollTop, ctx.signal);
}

const olderMessagesFlick: DeviceCheckScenario = {
  id: 'older-messages-flick',
  title: 'Older messages load during a flick',
  requires: 'touch',
  async run(ctx) {
    const conversationId = useStore.getState().currentConversation?.id ?? '';
    const hadOlder = useStore.getState().getMessagesPagination(conversationId)?.hasOlder === true;
    if (!hadOlder) return { status: 'skipped', measurements: {}, notes: ['no older messages to load'] };
    // A couple of screens from the top: one hard flick coasts into the load threshold
    ctx.container.scrollTop = LOAD_OLDER_MESSAGES_THRESHOLD_PX + 2 * ctx.container.clientHeight;
    await settle(ctx);
    const before = scrollWriteStats()['pagination-prepend'];
    const instruction = ctx.instruct('Flick the list down hard, towards older messages');
    const loaded = await waitUntil(
      () => scrollWriteStats()['pagination-prepend'].writes > before.writes,
      DEVICE_CHECK_FLICK_TIMEOUT_MS,
      ctx.signal
    );
    instruction.update('Hold still…');
    await settle(ctx);
    instruction.hide();
    return judge(
      'pagination-prepend',
      before,
      { older_loaded: loaded },
      'older messages never loaded - flick harder next time'
    );
  },
};

/** The fixture's resizing artifact (src/api/helpers/device_checks.py). */
function artifactCard(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>('.artifact-card');
}

async function countdown(ctx: DeviceCheckContext, text: string, totalMs: number): Promise<void> {
  const instruction = ctx.instruct(`${text} - ${Math.ceil(totalMs / COUNTDOWN_TICK_MS)} s`);
  try {
    for (let left = totalMs; left > 0; left -= COUNTDOWN_TICK_MS) {
      instruction.update(`${text} - ${Math.ceil(left / COUNTDOWN_TICK_MS)} s`);
      await waitUntil(() => false, Math.min(COUNTDOWN_TICK_MS, left), ctx.signal);
    }
  } finally {
    instruction.hide();
  }
}

const artifactResizeScroll: DeviceCheckScenario = {
  id: 'artifact-resize-scroll',
  title: 'Artifact resizes while you scroll',
  requires: 'touch',
  async run(ctx) {
    const card = artifactCard(ctx.container);
    if (!card) return { status: 'error', measurements: {}, notes: ['the test card is not in the list'] };
    // Start with the card in the middle of the screen, where the user can find it
    const offset = card.getBoundingClientRect().top - ctx.container.getBoundingClientRect().top;
    ctx.container.scrollTop += offset - ctx.container.clientHeight / 3;
    await settle(ctx);
    const before = scrollWriteStats()['artifact-resize'];
    await countdown(ctx, 'Scroll slowly up and down past the blue card', DEVICE_CHECK_ARTIFACT_SCROLL_MS);
    await settle(ctx);
    return judge(
      'artifact-resize',
      before,
      {},
      'the card never changed height above the screen - scroll it fully off the top'
    );
  },
};

/** Run after the keyboard steps (the keyboard is closed by then). */
export const GESTURE_SCENARIOS: readonly DeviceCheckScenario[] = [olderMessagesFlick, artifactResizeScroll];
