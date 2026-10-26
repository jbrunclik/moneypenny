/**
 * The device check run: fixture in, scenarios in order, results saved,
 * fixture out - also when the run is stopped or fails - and the user put
 * back on the conversation they had open.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import type { DeviceCheckScenario } from '@/core/device-checks/scenarios';
import type { Conversation } from '@/types/api';

const m = vi.hoisted(() => ({
  scenarios: [] as DeviceCheckScenario[],
  selectConversation: vi.fn<(id: string) => Promise<void>>(),
  createConversation: vi.fn(),
}));

vi.mock('@/core/conversation', () => ({
  selectConversation: m.selectConversation,
  createConversation: m.createConversation,
}));
vi.mock('@/core/device-checks/scenarios', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/core/device-checks/scenarios')>()),
  get DEVICE_CHECK_SCENARIOS() {
    return m.scenarios;
  },
}));

import { runDeviceChecks } from '@/core/device-checks/runner';
import { admin } from '@/api/admin';
import { useStore } from '@/state/store';

const FIXTURE_ID = 'fixture-1';

function conv(id: string): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '', messages: [] };
}

function scenario(id: string, run: DeviceCheckScenario['run'], requires: DeviceCheckScenario['requires'] = null): DeviceCheckScenario {
  return { id, title: id, requires, run };
}

const passed = (): Promise<{ status: 'passed'; measurements: Record<string, number>; notes: string[] }> =>
  Promise.resolve({ status: 'passed', measurements: { distance_from_bottom_px: 0 }, notes: [] });

let save: MockInstance<typeof admin.saveDeviceCheckRun>;
let remove: MockInstance<typeof admin.deleteDeviceCheckFixture>;

beforeEach(() => {
  document.body.innerHTML = '<div id="app" data-version="abc1234"><div id="messages"></div></div>';
  useStore.getState().setCurrentConversation(conv('previous'));
  m.selectConversation.mockImplementation((id) => {
    useStore.getState().setCurrentConversation(conv(id));
    return Promise.resolve();
  });
  vi.spyOn(admin, 'createDeviceCheckFixture').mockResolvedValue({ conversation_id: FIXTURE_ID, message_count: 80 });
  save = vi.spyOn(admin, 'saveDeviceCheckRun').mockImplementation((run) =>
    Promise.resolve({ ...run, id: 'r', passed: 0, failed: 0, skipped: 0, created_at: '' } as never)
  );
  remove = vi.spyOn(admin, 'deleteDeviceCheckFixture').mockResolvedValue();
});

afterEach(() => {
  vi.restoreAllMocks();
  m.selectConversation.mockReset();
  m.createConversation.mockReset();
});

describe('runDeviceChecks', () => {
  it('runs the suite on the fixture, saves it, deletes the fixture and goes back', async () => {
    const order: string[] = [];
    m.scenarios = [
      scenario('one', () => {
        order.push(`one on ${useStore.getState().currentConversation?.id}`);
        return passed();
      }),
      scenario('two', () => Promise.resolve({ status: 'failed', measurements: {}, notes: ['9px off'] })),
      scenario('keys', passed, 'software-keyboard'),
    ];
    const onClose = vi.fn();
    await runDeviceChecks({ onClose });

    expect(order).toEqual([`one on ${FIXTURE_ID}`]);
    const body = save.mock.calls[0]?.[0];
    expect(body?.build_marker).toMatch(/^kb\d+$/);
    expect(body?.app_version).toBe('abc1234');
    expect(body?.scenarios.map((s) => [s.id, s.status])).toEqual([
      ['one', 'passed'],
      ['two', 'failed'],
      ['keys', 'skipped'],
    ]);
    expect(body?.scenarios[2]?.notes).toEqual(['no software keyboard']);
    expect(m.selectConversation).toHaveBeenLastCalledWith('previous');
    expect(remove).toHaveBeenCalledOnce();
    expect(document.querySelector('.device-check-live')?.textContent).toBe('1/2 passed, 1 skipped');
    document.querySelector<HTMLButtonElement>('.device-check-close')?.click();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('records a scenario that throws as an error and carries on', async () => {
    m.scenarios = [scenario('boom', () => Promise.reject(new Error('x is undefined'))), scenario('after', passed)];
    await runDeviceChecks({ onClose: vi.fn() });
    const scenarios = save.mock.calls[0]?.[0].scenarios;
    expect(scenarios?.[0]).toMatchObject({ status: 'error', notes: ['x is undefined'] });
    expect(scenarios?.[1]?.status).toBe('passed');
  });

  it('Stop during a tap saves nothing but still deletes the fixture', async () => {
    m.scenarios = [scenario('tap', (ctx) => ctx.askTap('Tap', vi.fn()).then(passed), null)];
    const done = runDeviceChecks({ onClose: vi.fn() });
    await vi.waitFor(() => expect(document.querySelector('.device-check-tap')).not.toBeNull());
    document.querySelector<HTMLButtonElement>('.device-check-stop')?.click();
    await done;
    expect(save).not.toHaveBeenCalled();
    expect(remove).toHaveBeenCalledOnce();
    expect(m.selectConversation).toHaveBeenLastCalledWith('previous');
    expect(document.querySelector('.device-check-live')?.textContent).toBe('Stopped - nothing was saved.');
  });

  it('starts a new chat afterwards when none was open', async () => {
    useStore.getState().setCurrentConversation(null);
    m.scenarios = [scenario('one', passed)];
    await runDeviceChecks({ onClose: vi.fn() });
    expect(m.createConversation).toHaveBeenCalledOnce();
  });

  it('reports a failed fixture and still cleans up', async () => {
    vi.spyOn(admin, 'createDeviceCheckFixture').mockRejectedValue(new Error('500'));
    m.scenarios = [scenario('one', passed)];
    await runDeviceChecks({ onClose: vi.fn() });
    expect(save).not.toHaveBeenCalled();
    expect(remove).toHaveBeenCalledOnce();
    expect(m.selectConversation).not.toHaveBeenCalled();
    expect(document.querySelector('.device-check-live')?.textContent).toBe('The run failed - nothing was saved.');
  });

  it('says so when the run could not be saved', async () => {
    save.mockRejectedValue(new Error('500'));
    m.scenarios = [scenario('one', passed)];
    await runDeviceChecks({ onClose: vi.fn() });
    expect(document.querySelector('.device-check-live')?.textContent).toBe('The run could not be saved.');
  });
});
