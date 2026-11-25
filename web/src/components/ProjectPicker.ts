/**
 * Choosing a project for a chat (or several): an action sheet listing the
 * user's projects, then Remove from project (a chat in one), then New
 * project. The caller does the move.
 */
import { FOLDER_ICON, FOLDER_MINUS_ICON, PLUS_ICON } from '../utils/icons';
import type { Project } from '../types/api';
import { showActionSheet, type SheetAction } from './ActionSheet';

export interface ProjectPickerOptions {
  title: string;
  projects: Project[];
  /** The project the chat is in now (left out of the list) */
  currentProjectId?: string | null | undefined;
  onPick: (projectId: string) => void;
  onNew: () => void;
  /** Back to the main list - offered while the chat is in a project */
  onRemove?: () => void;
}

export function openProjectPicker(options: ProjectPickerOptions): void {
  const actions: SheetAction[] = options.projects
    .filter((p) => p.id !== options.currentProjectId)
    .map((p) => ({ label: p.name, icon: FOLDER_ICON, onSelect: () => options.onPick(p.id) }));
  if (options.currentProjectId && options.onRemove) {
    actions.push({ label: 'Remove from project', icon: FOLDER_MINUS_ICON, onSelect: options.onRemove });
  }
  actions.push({ label: 'New project…', icon: PLUS_ICON, onSelect: options.onNew });
  showActionSheet(options.title, actions);
}
