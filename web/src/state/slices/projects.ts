import type { Project } from '../../types/api';
import type { AppSlice } from '../store';

export interface ProjectsData {
  /** The user's projects (owned or shared with them), by name */
  projects: Project[];
  /** Owned-projects cap from the server */
  projectsLimit: number;
  isProjectView: boolean;
  /** The project page showing (with isProjectView) */
  activeProjectId: string | null;
}

export interface ProjectsSlice extends ProjectsData {
  setProjects: (projects: Project[], limit: number) => void;
  upsertProject: (project: Project) => void;
  removeProject: (projectId: string) => void;
  setActiveProjectId: (projectId: string | null) => void;
}

/** Initial projects state; also what logout resets to. */
export function initialProjectsData(): ProjectsData {
  return { projects: [], projectsLimit: 0, isProjectView: false, activeProjectId: null };
}

function byName(a: Project, b: Project): number {
  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
}

export const createProjectsSlice: AppSlice<ProjectsSlice> = (set) => ({
  ...initialProjectsData(),

  setProjects: (projects, projectsLimit) => set({ projects: [...projects].sort(byName), projectsLimit }),
  upsertProject: (project) =>
    set((state) => ({
      projects: [...state.projects.filter((p) => p.id !== project.id), project].sort(byName),
    })),
  removeProject: (projectId) =>
    set((state) => ({ projects: state.projects.filter((p) => p.id !== projectId) })),
  setActiveProjectId: (activeProjectId) => set({ activeProjectId }),
});
