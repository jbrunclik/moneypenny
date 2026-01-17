/**
 * Tests for routing race conditions.
 *
 * These tests verify the navigation token pattern that prevents stale async
 * operations from rendering content in the wrong view when users navigate rapidly.
 *
 * See docs/features/agents.md section "Routing Race Condition Prevention" for details.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../../src/state/store';

describe('Routing Race Conditions - Navigation Token Pattern', () => {
  beforeEach(() => {
    // Reset store state between tests
    useStore.setState({
      navigationToken: 0,
      isPlannerView: false,
      isAgentsView: false,
      currentConversation: null,
      commandCenterData: null,
      plannerDashboard: null,
    });
  });

  describe('Navigation Token Basics', () => {
    it('should start with token 0', () => {
      expect(useStore.getState().navigationToken).toBe(0);
    });

    it('should increment token on startNavigation', () => {
      const store = useStore.getState();
      const token1 = store.startNavigation();
      expect(token1).toBe(1);

      const token2 = store.startNavigation();
      expect(token2).toBe(2);
    });

    it('should validate matching token', () => {
      const store = useStore.getState();
      const token = store.startNavigation();
      expect(store.isNavigationValid(token)).toBe(true);
    });

    it('should invalidate old token after new navigation', () => {
      const store = useStore.getState();
      const oldToken = store.startNavigation();
      store.startNavigation(); // New navigation

      expect(store.isNavigationValid(oldToken)).toBe(false);
    });
  });

  describe('Rapid Navigation Scenarios', () => {
    it('should handle Agents → Planner → Agents rapid navigation', () => {
      const store = useStore.getState();

      // User clicks Agents
      const agentsToken1 = store.startNavigation();
      store.setIsAgentsView(true);

      // User quickly clicks Planner
      const plannerToken = store.startNavigation();
      store.setIsPlannerView(true);
      store.setIsAgentsView(false);

      // User quickly clicks Agents again
      const agentsToken2 = store.startNavigation();
      store.setIsAgentsView(true);
      store.setIsPlannerView(false);

      // First Agents navigation should be invalid
      expect(store.isNavigationValid(agentsToken1)).toBe(false);
      // Planner navigation should be invalid
      expect(store.isNavigationValid(plannerToken)).toBe(false);
      // Only the final Agents navigation should be valid
      expect(store.isNavigationValid(agentsToken2)).toBe(true);
    });

    it('should handle Conversation → Planner navigation', () => {
      const store = useStore.getState();

      // User clicks a conversation
      const convToken = store.startNavigation();

      // User quickly clicks Planner
      const plannerToken = store.startNavigation();
      store.setIsPlannerView(true);

      // Conversation navigation should be invalid
      expect(store.isNavigationValid(convToken)).toBe(false);
      // Planner navigation should be valid
      expect(store.isNavigationValid(plannerToken)).toBe(true);
    });

    it('should handle Planner → Agents → Conversation navigation', () => {
      const store = useStore.getState();

      // Navigate through all three views rapidly
      const plannerToken = store.startNavigation();
      const agentsToken = store.startNavigation();
      const convToken = store.startNavigation();

      // Only the final navigation should be valid
      expect(store.isNavigationValid(plannerToken)).toBe(false);
      expect(store.isNavigationValid(agentsToken)).toBe(false);
      expect(store.isNavigationValid(convToken)).toBe(true);
    });
  });

  describe('Async Operation Simulation', () => {
    it('should cancel stale operation after user navigated away', async () => {
      const store = useStore.getState();

      // Simulate starting Agents load
      const agentsToken = store.startNavigation();
      let shouldRender = false;

      // Simulate delay (async operation)
      await new Promise((resolve) => setTimeout(resolve, 10));

      // User navigated to Planner during the "load"
      store.startNavigation();
      store.setIsPlannerView(true);
      store.setIsAgentsView(false);

      // After "load" completes, check if should render
      if (store.isNavigationValid(agentsToken)) {
        shouldRender = true;
      }

      expect(shouldRender).toBe(false);
    });

    it('should render when user stayed on same view', async () => {
      const store = useStore.getState();

      // Simulate starting Agents load
      const agentsToken = store.startNavigation();
      store.setIsAgentsView(true);
      let shouldRender = false;

      // Simulate delay (async operation)
      await new Promise((resolve) => setTimeout(resolve, 10));

      // User stayed on Agents (no new navigation)

      // After "load" completes, check if should render
      if (store.isNavigationValid(agentsToken)) {
        shouldRender = true;
      }

      expect(shouldRender).toBe(true);
    });

    it('should handle multiple rapid navigations correctly', async () => {
      const store = useStore.getState();
      const tokens: number[] = [];
      const validAfterAll: boolean[] = [];

      // Simulate 5 rapid navigations
      for (let i = 0; i < 5; i++) {
        tokens.push(store.startNavigation());
        await new Promise((resolve) => setTimeout(resolve, 1));
      }

      // Check which tokens are still valid
      for (const token of tokens) {
        validAfterAll.push(store.isNavigationValid(token));
      }

      // Only the last token should be valid
      expect(validAfterAll).toEqual([false, false, false, false, true]);
    });
  });

  describe('Integration with View Flags', () => {
    it('should work alongside isPlannerView flag', () => {
      const store = useStore.getState();

      // Navigate to Planner
      const token = store.startNavigation();
      store.setIsPlannerView(true);

      // Both checks should indicate Planner is active
      expect(store.isNavigationValid(token)).toBe(true);
      expect(useStore.getState().isPlannerView).toBe(true);
    });

    it('should work alongside isAgentsView flag', () => {
      const store = useStore.getState();

      // Navigate to Agents
      const token = store.startNavigation();
      store.setIsAgentsView(true);

      // Both checks should indicate Agents is active
      expect(store.isNavigationValid(token)).toBe(true);
      expect(useStore.getState().isAgentsView).toBe(true);
    });
  });

  describe('Future Screens Pattern', () => {
    it('should handle hypothetical new screen navigation', () => {
      const store = useStore.getState();

      // Simulate navigating to a hypothetical "Settings" screen
      const settingsToken = store.startNavigation();
      // A hypothetical setIsSettingsView(true) would go here

      // User navigates away
      store.startNavigation();

      // The settings token should be invalid
      expect(store.isNavigationValid(settingsToken)).toBe(false);
    });
  });
});
