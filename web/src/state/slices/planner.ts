import type { PlannerConversation, PlannerDashboard } from '../../types/api';
import type { AppSlice } from '../store';

export interface PlannerData {
  plannerDashboard: PlannerDashboard | null;
  plannerConversation: PlannerConversation | null;
  plannerDashboardLastFetch: number | null; // Timestamp for cache invalidation
  isPlannerView: boolean;
}

export interface PlannerSlice extends PlannerData {
  setPlannerDashboard: (dashboard: PlannerDashboard | null) => void;
  setPlannerConversation: (conversation: PlannerConversation | null) => void;
  invalidatePlannerCache: () => void;
  clearPlannerState: () => void;
}

/** Initial planner state; also what logout and clearPlannerState reset to. */
export function initialPlannerData(): PlannerData {
  return {
    plannerDashboard: null,
    plannerConversation: null,
    plannerDashboardLastFetch: null,
    isPlannerView: false,
  };
}

export const createPlannerSlice: AppSlice<PlannerSlice> = (set) => ({
  ...initialPlannerData(),

  setPlannerDashboard: (plannerDashboard) =>
    set({ plannerDashboard, plannerDashboardLastFetch: plannerDashboard ? Date.now() : null }),
  setPlannerConversation: (plannerConversation) => set({ plannerConversation }),
  invalidatePlannerCache: () => set({ plannerDashboardLastFetch: null }),
  clearPlannerState: () => set(initialPlannerData()),
});
