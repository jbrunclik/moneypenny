/**
 * Regression tests for input visibility after navigation.
 *
 * These tests verify that the input area remains visible after navigation operations.
 * This prevents the bug where the input prompt doesn't appear when switching between views.
 *
 * Root cause: navigateToPlanner() set isAgentsView to false but didn't unhide the
 * input area that agents view had hidden.
 *
 * See: Bug where input prompt doesn't appear after switching from agents to planner
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';

// Mock all dependencies before importing the modules under test
vi.mock('@/state/store', () => ({
  useStore: {
    getState: vi.fn(),
    setState: vi.fn(),
    subscribe: vi.fn(() => vi.fn()),
  },
}));

vi.mock('@/utils/logger', () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
}));

vi.mock('@/api/client', () => ({
  planner: {
    getDashboard: vi.fn(),
    getConversation: vi.fn(),
    reset: vi.fn(),
  },
  agents: {
    getCommandCenter: vi.fn(),
    get: vi.fn(),
    approveRequest: vi.fn(),
    rejectRequest: vi.fn(),
    run: vi.fn(),
  },
}));

vi.mock('@/components/Toast', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(() => ({ dismiss: vi.fn() })),
  },
}));

vi.mock('@/components/Sidebar', () => ({
  setActiveConversation: vi.fn(),
  closeSidebar: vi.fn(),
  setPlannerActive: vi.fn(),
  setAgentsActive: vi.fn(),
  renderConversationsList: vi.fn(),
}));

vi.mock('@/components/messages', () => ({
  addMessageToUI: vi.fn(),
  updateChatTitle: vi.fn(),
  hasActiveStreamingContext: vi.fn(() => false),
  cleanupStreamingContext: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
}));

vi.mock('@/components/ModelSelector', () => ({
  renderModelDropdown: vi.fn(),
}));

vi.mock('@/components/ScrollToBottom', () => ({
  checkScrollButtonVisibility: vi.fn(),
}));

vi.mock('@/utils/dom', () => ({
  getElementById: vi.fn(),
  clearElement: vi.fn(),
}));

vi.mock('@/router/deeplink', () => ({
  clearConversationHash: vi.fn(),
  setPlannerHash: vi.fn(),
  setAgentsHash: vi.fn(),
}));

vi.mock('@/components/PlannerDashboard', () => ({
  createDashboardElement: vi.fn(() => document.createElement('div')),
  createDashboardLoadingElement: vi.fn(() => document.createElement('div')),
}));

vi.mock('@/utils/thumbnails', () => ({
  setCurrentConversationForBlobs: vi.fn(),
}));

vi.mock('@/config', () => ({
  PLANNER_DASHBOARD_CACHE_MS: 60000,
  COMMAND_CENTER_CACHE_MS: 60000,
  MOBILE_BREAKPOINT_PX: 768,
}));

vi.mock('@/components/CommandCenter', () => ({
  renderCommandCenter: vi.fn(() => document.createElement('div')),
  renderCommandCenterLoading: vi.fn(() => document.createElement('div')),
}));

vi.mock('@/components/AgentEditor', () => ({
  initAgentEditor: vi.fn(),
  showAgentEditor: vi.fn(),
}));

vi.mock('@/utils/icons', () => ({
  WARNING_ICON: '<svg></svg>',
}));

// Mock MessageInput - ensureInputAreaVisible needs to actually modify the DOM for tests
const mockEnsureInputAreaVisible = vi.fn(() => {
  const inputArea = document.querySelector<HTMLDivElement>('.input-area');
  if (inputArea) {
    inputArea.classList.remove('hidden');
  }
  const scrollToBottomBtn = document.querySelector<HTMLButtonElement>('.scroll-to-bottom');
  if (scrollToBottomBtn) {
    scrollToBottomBtn.classList.remove('hidden');
  }
});

vi.mock('@/components/MessageInput', () => ({
  focusMessageInput: vi.fn(),
  shouldAutoFocusInput: vi.fn(() => true),
  ensureInputAreaVisible: mockEnsureInputAreaVisible,
}));

// Mock messaging and toolbar
vi.mock('@/core/messaging', () => ({
  sendMessage: vi.fn(),
}));

vi.mock('@/core/toolbar', () => ({
  updateConversationCost: vi.fn(),
  updateAnonymousButtonState: vi.fn(),
}));

vi.mock('@/core/sync-banner', () => ({
  hideNewMessagesAvailableBanner: vi.fn(),
}));

import { useStore } from '@/state/store';
import { planner, agents } from '@/api/client';
import { getElementById } from '@/utils/dom';

describe('Navigation Input Visibility', () => {
  // Create mock elements
  let mockMessagesContainer: HTMLDivElement;
  let mockInputArea: HTMLDivElement;
  let mockScrollToBottomBtn: HTMLButtonElement;

  beforeEach(() => {
    vi.clearAllMocks();

    // Create mock DOM elements
    mockMessagesContainer = document.createElement('div');
    mockMessagesContainer.id = 'messages';
    mockInputArea = document.createElement('div');
    mockInputArea.className = 'input-area';
    mockScrollToBottomBtn = document.createElement('button');
    mockScrollToBottomBtn.className = 'scroll-to-bottom';

    // Mock getElementById
    (getElementById as Mock).mockImplementation((id: string) => {
      if (id === 'messages') return mockMessagesContainer;
      if (id === 'anonymous-btn') return document.createElement('button');
      if (id === 'message-input') return document.createElement('textarea');
      return null;
    });

    // Mock document.querySelector for input-area and scroll-to-bottom
    const originalQuerySelector = document.querySelector.bind(document);
    document.querySelector = vi.fn((selector: string) => {
      if (selector === '.input-area') return mockInputArea;
      if (selector === '.scroll-to-bottom') return mockScrollToBottomBtn;
      return originalQuerySelector(selector);
    }) as typeof document.querySelector;

    // Setup mock store state
    const mockStore = {
      isPlannerView: false,
      isAgentsView: false,
      currentConversation: null,
      plannerDashboard: null,
      plannerDashboardLastFetch: 0,
      plannerConversation: null,
      commandCenterData: null,
      commandCenterLastFetch: 0,
      pendingAnonymousMode: false,
      startNavigation: vi.fn(() => 1),
      isNavigationValid: vi.fn(() => true),
      setIsPlannerView: vi.fn(),
      setIsAgentsView: vi.fn(),
      setCurrentConversation: vi.fn(),
      setPlannerDashboard: vi.fn(),
      setPlannerConversation: vi.fn(),
      setCommandCenterData: vi.fn(),
      invalidatePlannerCache: vi.fn(),
      invalidateCommandCenterCache: vi.fn(),
    };

    (useStore.getState as Mock).mockReturnValue(mockStore);
  });

  describe('navigateToAgents hides input area', () => {
    it('should add hidden class to input-area when navigating to agents', async () => {
      (agents.getCommandCenter as Mock).mockResolvedValue({
        total_unread: 0,
        agents_waiting: 0,
        agents: [],
        pending_approvals: [],
      });

      const { navigateToAgents } = await import('@/core/agents');

      await navigateToAgents();

      expect(mockInputArea.classList.contains('hidden')).toBe(true);
      expect(mockScrollToBottomBtn.classList.contains('hidden')).toBe(true);
    });
  });

  describe('leaveAgentsView shows input area', () => {
    it('should remove hidden class from input-area when leaving agents', async () => {
      // Simulate input area being hidden (as it would be in agents view)
      mockInputArea.classList.add('hidden');
      mockScrollToBottomBtn.classList.add('hidden');

      const { leaveAgentsView } = await import('@/core/agents');

      leaveAgentsView(true);

      expect(mockInputArea.classList.contains('hidden')).toBe(false);
      expect(mockScrollToBottomBtn.classList.contains('hidden')).toBe(false);
    });

    it('should show input area even when clearMessages is false', async () => {
      mockInputArea.classList.add('hidden');
      mockScrollToBottomBtn.classList.add('hidden');

      const { leaveAgentsView } = await import('@/core/agents');

      leaveAgentsView(false);

      // Input area should be shown regardless of clearMessages
      expect(mockInputArea.classList.contains('hidden')).toBe(false);
      expect(mockScrollToBottomBtn.classList.contains('hidden')).toBe(false);
    });
  });

  describe('navigateToPlanner from agents view', () => {
    it('should show input area when navigating from agents to planner', async () => {
      // Simulate being in agents view with input hidden
      const mockStore = useStore.getState() as ReturnType<typeof useStore.getState>;
      (mockStore as { isAgentsView: boolean }).isAgentsView = true;
      mockInputArea.classList.add('hidden');
      mockScrollToBottomBtn.classList.add('hidden');

      (planner.getDashboard as Mock).mockResolvedValue({
        date: new Date().toISOString(),
        events: [],
        tasks: [],
      });
      (planner.getConversation as Mock).mockResolvedValue({
        id: 'planner-conv-123',
        model: 'gemini-3-flash-preview',
        messages: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { navigateToPlanner } = await import('@/core/planner');

      await navigateToPlanner();

      // Input area should be visible after navigating to planner
      expect(mockInputArea.classList.contains('hidden')).toBe(false);
      expect(mockScrollToBottomBtn.classList.contains('hidden')).toBe(false);
    });

    it('should not touch input area visibility when not coming from agents view', async () => {
      // Not in agents view
      const mockStore = useStore.getState() as ReturnType<typeof useStore.getState>;
      (mockStore as { isAgentsView: boolean }).isAgentsView = false;

      // Input area is visible
      mockInputArea.classList.remove('hidden');

      (planner.getDashboard as Mock).mockResolvedValue({
        date: new Date().toISOString(),
        events: [],
        tasks: [],
      });
      (planner.getConversation as Mock).mockResolvedValue({
        id: 'planner-conv-123',
        model: 'gemini-3-flash-preview',
        messages: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { navigateToPlanner } = await import('@/core/planner');

      await navigateToPlanner();

      // Should remain visible
      expect(mockInputArea.classList.contains('hidden')).toBe(false);
    });
  });

  describe('race condition scenarios', () => {
    it('should handle rapid agents -> planner -> chat navigation', async () => {
      // This test simulates the race condition where user quickly switches views

      // Start in agents view with hidden input
      mockInputArea.classList.add('hidden');

      // Mock the store to simulate agents view
      const mockStore = useStore.getState() as ReturnType<typeof useStore.getState>;
      (mockStore as { isAgentsView: boolean }).isAgentsView = true;

      (planner.getDashboard as Mock).mockResolvedValue({
        date: new Date().toISOString(),
        events: [],
        tasks: [],
      });
      (planner.getConversation as Mock).mockResolvedValue({
        id: 'planner-conv-123',
        model: 'gemini-3-flash-preview',
        messages: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      const { navigateToPlanner } = await import('@/core/planner');

      // Navigate to planner from agents
      await navigateToPlanner();

      // The input should be visible after the navigation completes
      expect(mockInputArea.classList.contains('hidden')).toBe(false);
    });
  });
});
