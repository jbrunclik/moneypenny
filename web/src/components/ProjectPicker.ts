/**
 * Choosing a project for a chat (or several): an action sheet listing the
 * user's projects, then New project. The caller does the move.
 */
import { FOLDER_ICON, PLUS_ICON } from '../utils/icons';
import type { Project } from '../types/api';
import { showActionSheet, type SheetAction } from './ActionSheet';

export interface ProjectPickerOptions {
  title: string;
  projects: Project[];
  /** The project the chat is in now (left out of the list) */
  currentProjectId?: string | null | undefined;
  onPick: (projectId: string) => void;
  onNew: () => void;
}

export function openProjectPicker(options: ProjectPickerOptions): void {
  const actions: SheetAction[] = options.projects
    .filter((p) => p.id !== options.currentProjectId)
    .map((p) => ({ label: p.name, icon: FOLDER_ICON, onSelect: () => options.onPick(p.id) }));
  actions.push({ label: 'New project…', icon: PLUS_ICON, onSelect: options.onNew });
  showActionSheet(options.title, actions);
}
