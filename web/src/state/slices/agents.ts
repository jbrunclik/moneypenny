import type { JobsOverviewResponse } from '../../types/api';
import type { AppSlice } from '../store';

export interface AgentsData {
  commandCenterData: JobsOverviewResponse | null;
  commandCenterLastFetch: number | null; // Timestamp for cache invalidation
  isAgentsView: boolean;
}

export interface AgentsSlice extends AgentsData {
  setCommandCenterData: (data: JobsOverviewResponse | null) => void;
  invalidateCommandCenterCache: () => void;
  clearAgentsState: () => void;
}

/** Initial agents state; also what logout and clearAgentsState reset to. */
export function initialAgentsData(): AgentsData {
  return {
    commandCenterData: null,
    commandCenterLastFetch: null,
    isAgentsView: false,
  };
}

export const createAgentsSlice: AppSlice<AgentsSlice> = (set) => ({
  ...initialAgentsData(),

  setCommandCenterData: (commandCenterData) =>
    set({ commandCenterData, commandCenterLastFetch: commandCenterData ? Date.now() : null }),
  invalidateCommandCenterCache: () => set({ commandCenterLastFetch: null }),
  clearAgentsState: () => set(initialAgentsData()),
});
