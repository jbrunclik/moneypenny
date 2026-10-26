/**
 * Agent editor: the form reflects the agent being edited, and Save
 * validates the name and schedule, then sends exactly the filled fields
 * (keeping unrestricted tool access unrestricted unless changed).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const api = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  getCommandCenter: vi.fn(),
  settingsGet: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('@/api/agents', () => ({
  agents: { create: api.create, update: api.update, delete: api.delete, getCommandCenter: api.getCommandCenter },
  aiAssist: { parseSchedule: vi.fn(), enhancePrompt: vi.fn() },
}));
vi.mock('@/api/settings', () => ({ settings: { get: api.settingsGet } }));
vi.mock('@/components/Toast', () => ({ toast: { success: api.toastSuccess, error: api.toastError } }));

import { useStore } from '@/state/store';
import { showAgentEditor } from '@/components/AgentEditor';
import type { Agent } from '@/types/api';

function agent(extra: Partial<Agent> = {}): Agent {
  return {
    id: 'a1',
    name: 'Watcher',
    description: 'Checks things',
    system_prompt: 'Be brief',
    schedule: '0 9 * * 1-5',
    timezone: 'Europe/Prague',
    enabled: false,
    fresh_context: false,
    tool_permissions: ['todoist'],
    model: 'm2',
    budget_limit: 1.5,
    ...extra,
  } as unknown as Agent;
}

const modal = () => document.getElementById('agent-editor-modal') as HTMLElement;
const field = <T extends HTMLElement>(sel: string) => modal().querySelector<T>(sel) as T;
const save = () => field<HTMLButtonElement>('.agent-editor-save').click();

/** Open the editor; resolves once the form is rendered, with the editor's eventual result. */
async function open(a?: Agent): Promise<{ result: Promise<Agent | null> }> {
  const result = showAgentEditor(a);
  await vi.waitFor(() => expect(modal()?.querySelector('.agent-editor')).toBeTruthy());
  return { result };
}

describe('AgentEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.getElementById('agent-editor-modal')?.replaceChildren();
    api.settingsGet.mockResolvedValue({ whatsapp_available: false, whatsapp_phone: null });
    useStore.setState({
      models: [
        { id: 'm1', name: 'Model One', short_name: 'One' },
        { id: 'm2', name: 'Model Two', short_name: 'Two' },
      ] as never,
      defaultModel: 'm1',
    });
  });

  it('fills the form from the agent being edited', async () => {
    await open(agent());

    expect(field('#agent-editor-title').textContent).toBe('Edit Agent');
    expect(field<HTMLInputElement>('#agent-name').value).toBe('Watcher');
    expect(field<HTMLTextAreaElement>('#agent-description').value).toBe('Checks things');
    expect(field<HTMLTextAreaElement>('#agent-system-prompt').value).toBe('Be brief');
    expect(field('.schedule-preset-chip.selected').textContent?.trim()).toBe('Weekdays');
    expect(field('#schedule-explanation').textContent).toBe('Weekdays at 9:00 AM');
    expect(field('#schedule-result').classList.contains('hidden')).toBe(false);
    expect(field<HTMLSelectElement>('#agent-timezone').value).toBe('Europe/Prague');
    expect(field<HTMLSelectElement>('#agent-model').value).toBe('m2');
    expect(field<HTMLInputElement>('#agent-budget-limit').value).toBe('1.5');
    const checked = [...modal().querySelectorAll<HTMLInputElement>('input[name="tool-permission"]:checked')];
    expect(checked.map((c) => c.value)).toEqual(['todoist']);
    expect(modal().querySelector('input[value="whatsapp"]')).toBeNull();
    expect(field<HTMLInputElement>('#agent-fresh-context').checked).toBe(false);
    expect(field<HTMLInputElement>('#agent-enabled').checked).toBe(false);
    expect(modal().querySelector('.agent-editor-delete')).not.toBeNull();
    expect(field('.agent-editor-save').textContent?.trim()).toBe('Save Changes');
  });

  it('starts a new agent with defaults', async () => {
    await open();

    expect(field('#agent-editor-title').textContent).toBe('Create Agent');
    expect(field<HTMLInputElement>('#agent-name').value).toBe('');
    expect(field('.schedule-preset-chip.selected').textContent?.trim()).toBe('Manual');
    expect(field('#schedule-result').classList.contains('hidden')).toBe(true);
    expect(field<HTMLSelectElement>('#agent-model').value).toBe('m1');
    expect(field<HTMLInputElement>('#agent-budget-limit').value).toBe('');
    expect(field<HTMLInputElement>('#agent-fresh-context').checked).toBe(true);
    expect(field<HTMLInputElement>('#agent-enabled').checked).toBe(true);
    expect(modal().querySelectorAll('input[name="tool-permission"]:checked')).toHaveLength(0);
    expect(modal().querySelector('.agent-editor-delete')).toBeNull();
    expect(field('.agent-editor-save').textContent?.trim()).toBe('Create Agent');
  });

  it('marks a custom schedule and offers WhatsApp when it is set up', async () => {
    api.settingsGet.mockResolvedValue({ whatsapp_available: true, whatsapp_phone: '+420' });
    await open(agent({ schedule: '30 6 * * *' }));

    expect(field('#schedule-explanation').textContent).toBe('Custom schedule');
    expect(modal().querySelector('.schedule-preset-chip.selected')).toBeNull();
    expect(field<HTMLInputElement>('#agent-cron').value).toBe('30 6 * * *');
    expect(modal().querySelector('input[value="whatsapp"]')).not.toBeNull();
  });

  it('shows every tool checked for unrestricted access', async () => {
    await open(agent({ tool_permissions: null }));

    const boxes = [...modal().querySelectorAll<HTMLInputElement>('input[name="tool-permission"]')];
    expect(boxes.every((b) => b.checked)).toBe(true);
    expect(modal().textContent).toContain('unrestricted tool access');
  });

  it('requires a name', async () => {
    await open();
    save();

    expect(field('#agent-name').classList.contains('form-input--error')).toBe(true);
    expect(field('#agent-name-error').classList.contains('form-error--hidden')).toBe(false);
    expect(api.create).not.toHaveBeenCalled();
  });

  it('rejects an invalid schedule and opens the cron editor', async () => {
    await open();
    field<HTMLInputElement>('#agent-name').value = 'New';
    field<HTMLInputElement>('#agent-schedule-value').value = '99 * * * *';
    save();

    expect(field('#agent-cron').classList.contains('form-input--error')).toBe(true);
    expect(field('#cron-edit-container').classList.contains('hidden')).toBe(false);
    expect(api.create).not.toHaveBeenCalled();
  });

  it('creates an agent with only the filled fields', async () => {
    const created = agent({ id: 'new' });
    api.create.mockResolvedValue(created);
    const { result } = await open();
    field<HTMLInputElement>('#agent-name').value = '  New  ';
    field<HTMLInputElement>('#agent-budget-limit').value = '2';
    modal().querySelector<HTMLInputElement>('input[value="todoist"]')!.checked = true;
    save();

    await vi.waitFor(() => expect(api.create).toHaveBeenCalled());
    expect(api.create).toHaveBeenCalledWith({
      name: 'New',
      timezone: expect.any(String),
      model: 'm1',
      budget_limit: 2,
      enabled: true,
      fresh_context: true,
      tool_permissions: ['todoist'],
    });
    expect(api.toastSuccess).toHaveBeenCalledWith('Agent created');
    await expect(result).resolves.toBe(created);
  });

  it('updates an agent, keeping untouched unrestricted access unrestricted', async () => {
    api.update.mockResolvedValue(agent());
    await open(agent({ tool_permissions: null }));
    save();

    await vi.waitFor(() => expect(api.update).toHaveBeenCalled());
    expect(api.update).toHaveBeenCalledWith('a1', {
      name: 'Watcher',
      description: 'Checks things',
      system_prompt: 'Be brief',
      schedule: '0 9 * * 1-5',
      timezone: 'Europe/Prague',
      model: 'm2',
      budget_limit: 1.5,
      enabled: false,
      fresh_context: false,
    });
  });

  it('sends the selection once unrestricted access is changed', async () => {
    api.update.mockResolvedValue(agent());
    await open(agent({ tool_permissions: null }));
    const box = modal().querySelector<HTMLInputElement>('input[value="todoist"]')!;
    box.checked = false;
    box.dispatchEvent(new Event('change', { bubbles: true }));
    save();

    await vi.waitFor(() => expect(api.update).toHaveBeenCalled());
    expect(api.update.mock.calls[0]?.[1].tool_permissions).not.toContain('todoist');
  });

  it('re-enables Save after a failed save', async () => {
    api.update.mockRejectedValue(new Error('down'));
    await open(agent());
    save();

    await vi.waitFor(() => expect(api.toastError).toHaveBeenCalledWith('Failed to save agent'));
    const btn = field<HTMLButtonElement>('.agent-editor-save');
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe('Save Changes');
  });
});
