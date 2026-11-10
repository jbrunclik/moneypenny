/**
 * The gesture steps of the device checks, outside a device: what they report
 * when there is nothing to measure (the real gestures need an iPhone).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GESTURE_SCENARIOS } from '@/core/device-checks/gesture-scenarios';
import type { DeviceCheckContext } from '@/core/device-checks/scenarios';
import { _resetScrollWriteStats, writeScrollTop } from '@/utils/scroll-writes';
import { DEVICE_CHECK_ARTIFACT_SCROLL_MS } from '@/config';

const [flick, artifact] = GESTURE_SCENARIOS;

function context(container: HTMLElement): DeviceCheckContext & { texts: string[] } {
  const texts: string[] = [];
  return {
    container,
    signal: new AbortController().signal,
    askTap: () => Promise.resolve(),
    instruct(text) {
      texts.push(text);
      return { update: (next: string) => texts.push(next), hide: () => texts.push('(hidden)') };
    },
    shared: { turnEl: null, keyboardShown: false },
    texts,
  };
}

beforeEach(() => {
  _resetScrollWriteStats();
  document.body.innerHTML = '<div id="messages"></div>';
});

afterEach(() => {
  vi.useRealTimers();
});

describe('gesture steps', () => {
  it('run in order: the flick, then the artifact', () => {
    expect(GESTURE_SCENARIOS.map((s) => [s.id, s.requires])).toEqual([
      ['older-messages-flick', 'touch'],
      ['artifact-resize-scroll', 'touch'],
    ]);
  });

  it('the flick is skipped when the chat has no older messages to load', async () => {
    const outcome = await flick!.run(context(document.getElementById('messages')!));
    expect(outcome).toMatchObject({ status: 'skipped', notes: ['no older messages to load'] });
  });

  it('the artifact step reports an error when the test card is missing', async () => {
    const outcome = await artifact!.run(context(document.getElementById('messages')!));
    expect(outcome).toMatchObject({ status: 'error', notes: ['the test card is not in the list'] });
  });

  it('the artifact step asks with a countdown and judges the corrections made meanwhile', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance', 'requestAnimationFrame'] });
    const container = document.getElementById('messages')!;
    container.appendChild(document.createElement('div')).className = 'artifact-card';
    // A tall list whose scroll writes are ignored, like iOS mid-coast
    Object.defineProperty(container, 'scrollHeight', { value: 5000 });
    Object.defineProperty(container, 'clientHeight', { value: 800 });
    Object.defineProperty(container, 'scrollTop', { get: () => 0, set: () => undefined });
    const ctx = context(container);
    const running = artifact!.run(ctx);
    // A correction during the countdown that the browser ignored (jsdom keeps scrollTop at 0)
    await vi.advanceTimersByTimeAsync(1500);
    writeScrollTop(container, 400, 'artifact-resize');
    await vi.advanceTimersByTimeAsync(DEVICE_CHECK_ARTIFACT_SCROLL_MS + 10_000);
    const outcome = await running;

    expect(ctx.texts[0]).toBe('Scroll slowly up and down past the blue card - 6 s');
    expect(ctx.texts).toContain('(hidden)');
    expect(outcome.status).toBe('failed');
    expect(outcome.measurements).toMatchObject({ verified: 1, dropped: 1 });
  });
});
