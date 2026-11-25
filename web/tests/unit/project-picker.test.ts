/**
 * ProjectPicker: the user's projects (minus the chat's own), then New project.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Project } from '@/types/api';

const sheet = vi.hoisted(() => ({ show: vi.fn() }));
vi.mock('@/components/ActionSheet', () => ({ showActionSheet: sheet.show }));

import { openProjectPicker } from '@/components/ProjectPicker';

const project = (id: string, name: string): Project => ({
  id,
  name,
  owner_id: 'u',
  is_owner: true,
  shared: false,
  member_names: [],
  member_ids: ['u'],
  chat_count: 0,
  unread_count: 0,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
  deleted_at: null,
});

describe('openProjectPicker', () => {
  beforeEach(() => sheet.show.mockClear());

  it('lists projects then New project, leaving out the current one', () => {
    const onPick = vi.fn();
    const onNew = vi.fn();
    openProjectPicker({
      title: 'Move to project',
      projects: [project('p1', 'Bikes'), project('p2', 'Home')],
      currentProjectId: 'p1',
      onPick,
      onNew,
    });

    const [title, actions] = sheet.show.mock.calls[0] as [string, Array<{ label: string; onSelect: () => void }>];
    expect(title).toBe('Move to project');
    expect(actions.map((a) => a.label)).toEqual(['Home', 'New project…']);
    actions[0]?.onSelect();
    expect(onPick).toHaveBeenCalledWith('p2');
    actions[1]?.onSelect();
    expect(onNew).toHaveBeenCalled();
  });

  it('offers Remove from project for a chat in a project', () => {
    const onRemove = vi.fn();
    openProjectPicker({
      title: 'Move to project',
      projects: [project('p1', 'Bikes')],
      currentProjectId: 'p1',
      onPick: vi.fn(),
      onNew: vi.fn(),
      onRemove,
    });

    const [, actions] = sheet.show.mock.calls[0] as [string, Array<{ label: string; onSelect: () => void }>];
    expect(actions.map((a) => a.label)).toEqual(['Remove from project', 'New project…']);
    actions[0]?.onSelect();
    expect(onRemove).toHaveBeenCalled();
  });

  it('offers no Remove for a chat in no project', () => {
    openProjectPicker({
      title: 'Move to project',
      projects: [project('p1', 'Bikes')],
      currentProjectId: null,
      onPick: vi.fn(),
      onNew: vi.fn(),
      onRemove: vi.fn(),
    });

    const [, actions] = sheet.show.mock.calls[0] as [string, Array<{ label: string }>];
    expect(actions.map((a) => a.label)).toEqual(['Bikes', 'New project…']);
  });
});
