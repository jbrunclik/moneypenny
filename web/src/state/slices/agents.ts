import type { Agent, CommandCenterResponse } from '../../types/api';
import type { AppSlice } from '../store';

export interface AgentsData {
  agents: Agent[];
  commandCenterData: CommandCenterResponse | null;
  commandCenterLastFetch: number | null; // Timestamp for cache invalidation
  isAgentsView: boolean;
}

export interface AgentsSlice extends AgentsData {
  setAgents: (agents: Agent[]) => void;
  addAgent: (agent: Agent) => void;
  updateAgent: (id: string, updates: Partial<Agent>) => void;
  removeAgent: (id: string) => void;
  setCommandCenterData: (data: CommandCenterResponse | null) => void;
  invalidateCommandCenterCache: () => void;
  clearAgentsState: () => void;
}

/** Initial agents state; also what logout and clearAgentsState reset to. */
export function initialAgentsData(): AgentsData {
  return {
    agents: [],
    commandCenterData: null,
    commandCenterLastFetch: null,
    isAgentsView: false,
  };
}

export const createAgentsSlice: AppSlice<AgentsSlice> = (set) => ({
  ...initialAgentsData(),

  setAgents: (agents) => set({ agents }),
  addAgent: (agent) => set((state) => ({ agents: [agent, ...state.agents] })),
  updateAgent: (id, updates) =>
    set((state) => ({
      agents: state.agents.map((a) => (a.id === id ? { ...a, ...updates } : a)),
    })),
  removeAgent: (id) => set((state) => ({ agents: state.agents.filter((a) => a.id !== id) })),
  setCommandCenterData: (commandCenterData) =>
    set({ commandCenterData, commandCenterLastFetch: commandCenterData ? Date.now() : null }),
  invalidateCommandCenterCache: () => set({ commandCenterLastFetch: null }),
  clearAgentsState: () => set(initialAgentsData()),
});
