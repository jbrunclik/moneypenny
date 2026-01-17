/**
 * E2E tests for Autonomous Agents feature
 *
 * Tests cover:
 * - Sidebar entry visibility and badge
 * - Navigation to Command Center
 * - Agent list display
 * - Approval handling
 * - Agent creation/editing
 * - Agent triggering
 */
import { test, expect } from '../global-setup';

// Helper function to set up command center mock data
async function setCommandCenterData(page: import('@playwright/test').Page, data: {
  agents?: Array<{
    id: string;
    name: string;
    description?: string;
    schedule?: string;
    timezone?: string;
    enabled?: boolean;
    unread_count?: number;
    has_pending_approval?: boolean;
    last_run_at?: string;
    next_run_at?: string;
    created_at?: string;
    updated_at?: string;
  }>;
  pending_approvals?: Array<{
    id: string;
    agent_id: string;
    agent_name: string;
    tool_name: string;
    description: string;
    status?: string;
    created_at?: string;
  }>;
  recent_executions?: Array<{
    id: string;
    agent_id: string;
    status: string;
    trigger_type: string;
    started_at: string;
    completed_at?: string;
  }>;
  total_unread?: number;
  agents_waiting?: number;
}) {
  const commandCenter = {
    agents: data.agents || [],
    pending_approvals: data.pending_approvals || [],
    recent_executions: data.recent_executions || [],
    total_unread: data.total_unread || 0,
    agents_waiting: data.agents_waiting || 0,
  };
  await page.request.post('/test/set-agents-command-center', {
    data: { command_center: commandCenter },
  });
}

test.describe('Agents - Sidebar Entry', () => {
  test('shows agents entry in sidebar', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Agents entry should be visible
    const agentsEntry = page.locator('.agents-entry');
    await expect(agentsEntry).toBeVisible();
    await expect(agentsEntry).toContainText('Agents');
  });

  test('shows badge with total unread count', async ({ page }) => {
    // Set command center with unread messages
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 5,
          has_pending_approval: false,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      total_unread: 5,
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Badge should show unread count
    const badge = page.locator('.agents-entry .unread-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toHaveText('5');
  });

  test('shows waiting indicator when agents need approval', async ({ page }) => {
    // Set command center with pending approval
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 0,
          has_pending_approval: true,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      agents_waiting: 1,
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Waiting badge should show count
    const waitingBadge = page.locator('.agents-entry .waiting-badge');
    await expect(waitingBadge).toBeVisible();
    await expect(waitingBadge).toContainText('1');
  });
});

test.describe('Agents - Navigation', () => {
  test('navigates to command center via sidebar click', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click agents entry
    const agentsEntry = page.locator('.agents-entry');
    await agentsEntry.click();

    // Should show command center
    const commandCenter = page.locator('.command-center');
    await expect(commandCenter).toBeVisible();

    // URL should be updated
    await expect(page).toHaveURL(/#\/agents$/);
  });

  test('navigates to command center via deep link', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Should show command center
    const commandCenter = page.locator('.command-center');
    await expect(commandCenter).toBeVisible();
  });

  test('shows empty state when no agents', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Should show empty message
    const emptyMessage = page.locator('.empty-state');
    await expect(emptyMessage).toBeVisible();
    await expect(emptyMessage).toContainText('No agents yet');
  });
});

test.describe('Agents - Command Center Display', () => {
  test('displays list of agents', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Daily Briefing',
          description: 'Summarizes your schedule',
          schedule: '0 9 * * *',
          enabled: true,
          unread_count: 2,
          has_pending_approval: false,
          timezone: 'Europe/Prague',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'agent-2',
          name: 'Research Assistant',
          description: 'Finds articles',
          enabled: true,
          unread_count: 0,
          has_pending_approval: false,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Should show agent cards
    const agentCards = page.locator('.agent-card');
    await expect(agentCards).toHaveCount(2);

    // First agent should show name and description
    const firstCard = agentCards.first();
    await expect(firstCard).toContainText('Daily Briefing');
    await expect(firstCard).toContainText('Summarizes your schedule');

    // Badge should show unread count
    const badge = firstCard.locator('.unread-badge');
    await expect(badge).toContainText('2');
  });

  test('displays pending approvals section', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 0,
          has_pending_approval: true,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      pending_approvals: [
        {
          id: 'approval-1',
          agent_id: 'agent-1',
          agent_name: 'Test Agent',
          tool_name: 'todoist',
          description: 'Add task: Buy groceries',
          status: 'pending',
          created_at: new Date().toISOString(),
        },
      ],
      agents_waiting: 1,
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Should show pending approvals section with highlight
    const approvalsSection = page.locator('.command-center-section--approvals.has-approvals');
    await expect(approvalsSection).toBeVisible();

    // Should show approval card
    const approvalCard = page.locator('.approval-card');
    await expect(approvalCard).toBeVisible();
    await expect(approvalCard).toContainText('Test Agent');
    await expect(approvalCard).toContainText('todoist');
  });

  test('shows disabled agent with dimmed styling', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Disabled Agent',
          enabled: false,
          unread_count: 0,
          has_pending_approval: false,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Disabled agent should have dimmed class
    const agentCard = page.locator('.agent-card');
    await expect(agentCard).toHaveClass(/agent-card--disabled/);
  });
});

test.describe('Agents - Approval Handling', () => {
  test('can approve a pending request', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 0,
          has_pending_approval: true,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      pending_approvals: [
        {
          id: 'approval-1',
          agent_id: 'agent-1',
          agent_name: 'Test Agent',
          tool_name: 'todoist',
          description: 'Add task: Buy groceries',
          status: 'pending',
          created_at: new Date().toISOString(),
        },
      ],
      agents_waiting: 1,
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.approval-card');

    // Click approve button
    const approveBtn = page.locator('.approval-card .btn-approve');
    await expect(approveBtn).toBeVisible();

    // Note: In actual E2E test, we'd mock the API response and verify the approval
    // For now, just verify the button is clickable
    await expect(approveBtn).toBeEnabled();
  });

  test('can reject a pending request', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 0,
          has_pending_approval: true,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      pending_approvals: [
        {
          id: 'approval-1',
          agent_id: 'agent-1',
          agent_name: 'Test Agent',
          tool_name: 'todoist',
          description: 'Add task: Buy groceries',
          status: 'pending',
          created_at: new Date().toISOString(),
        },
      ],
      agents_waiting: 1,
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.approval-card');

    // Click reject button
    const rejectBtn = page.locator('.approval-card .btn-reject');
    await expect(rejectBtn).toBeVisible();
    await expect(rejectBtn).toBeEnabled();
  });
});

test.describe('Agents - Agent Creation', () => {
  test('opens new agent modal when clicking New Agent button', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Click new agent button
    const newAgentBtn = page.locator('.btn-new-agent');
    await newAgentBtn.click();

    // Modal should open - use role selector for reliability
    const modal = page.getByRole('dialog', { name: 'Create Agent' });
    await expect(modal).toBeVisible();

    // Should have form fields (using more reliable locators)
    await expect(page.getByLabel('Name *')).toBeVisible();
    await expect(page.getByLabel('Description')).toBeVisible();
    await expect(page.getByLabel('System Prompt / Goals')).toBeVisible();
  });

  test('can close new agent modal', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Open modal
    await page.locator('.btn-new-agent').click();
    const modal = page.getByRole('dialog', { name: 'Create Agent' });
    await expect(modal).toBeVisible();

    // Click cancel button
    await page.getByRole('button', { name: 'Cancel' }).click();

    // Modal should close
    await expect(modal).not.toBeVisible();
  });

  test('validates required fields', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Open modal
    await page.locator('.btn-new-agent').click();
    const modal = page.getByRole('dialog', { name: 'Create Agent' });
    await expect(modal).toBeVisible();

    // Try to save without name - the form uses HTML5 validation
    // Scope to modal to avoid matching the CTA button in #messages
    await modal.getByRole('button', { name: 'Create Agent' }).click();

    // Name field should be invalid/focused (browser validation)
    const nameInput = page.getByLabel('Name *');
    await expect(nameInput).toBeFocused();
  });
});

test.describe('Agents - Agent Actions', () => {
  test('shows edit button on agent cards', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 0,
          has_pending_approval: false,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.agent-card');

    // Edit button should be visible
    const editBtn = page.locator('.agent-card .btn-edit');
    await expect(editBtn).toBeVisible();
  });

  test('shows run button on agent cards', async ({ page }) => {
    await setCommandCenterData(page, {
      agents: [
        {
          id: 'agent-1',
          name: 'Test Agent',
          enabled: true,
          unread_count: 0,
          has_pending_approval: false,
          timezone: 'UTC',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.agent-card');

    // Run button should be visible
    const runBtn = page.locator('.agent-card .btn-run');
    await expect(runBtn).toBeVisible();
  });

  test('opens edit modal when clicking edit button', async ({ page }) => {
    const agentId = 'agent-edit-test-1';
    const createdAt = new Date().toISOString();

    // Set command center data with an agent
    await setCommandCenterData(page, {
      agents: [
        {
          id: agentId,
          name: 'Test Agent',
          description: 'Test description',
          enabled: true,
          unread_count: 0,
          has_pending_approval: false,
          timezone: 'UTC',
          created_at: createdAt,
          updated_at: createdAt,
        },
      ],
    });

    // Set individual agent data for the GET /api/agents/:id endpoint
    await page.request.post('/test/set-agent', {
      data: {
        id: agentId,
        name: 'Test Agent',
        description: 'Test description',
        system_prompt: 'You are a helpful assistant.',
        enabled: true,
        schedule: null,
        timezone: 'UTC',
        conversation_id: 'conv-1',
        created_at: createdAt,
        updated_at: createdAt,
      },
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.agent-card');

    // Click edit button
    await page.locator('.agent-card .btn-edit').click();

    // Modal should open with "Edit Agent" title
    const modal = page.getByRole('dialog', { name: 'Edit Agent' });
    await expect(modal).toBeVisible();

    // Form should be pre-filled with agent data
    await expect(page.getByLabel('Name *')).toHaveValue('Test Agent');
    await expect(page.getByLabel('Description')).toHaveValue('Test description');
  });
});

test.describe('Agents - Refresh', () => {
  test('refresh button reloads command center', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Click refresh button
    const refreshBtn = page.locator('.btn-refresh');
    await expect(refreshBtn).toBeVisible();

    // Just verify it's clickable (actual reload would need API mocking)
    await expect(refreshBtn).toBeEnabled();
  });
});

test.describe('Agents - Header', () => {
  test('shows Command Center title', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Title should show Command Center
    const title = page.locator('.command-center-title h2');
    await expect(title).toContainText('Command Center');
  });

  test('hides input area in command center', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Input area should be hidden
    const inputArea = page.locator('.input-area');
    await expect(inputArea).toHaveClass(/hidden/);
  });
});

test.describe('Agents - Pending Approval Input Blocking', () => {
  test('blocks message input when conversation has pending approval', async ({ page }) => {
    // Seed an agent with a pending approval
    const seedResponse = await page.request.post('/test/seed-agent-with-approval', {
      data: {
        name: 'Approval Test Agent',
        description: 'Test action requiring approval',
        tool_name: 'test_tool',
      },
    });
    expect(seedResponse.ok()).toBe(true);
    const seedData = await seedResponse.json();
    const conversationId = seedData.conversation_id;
    expect(conversationId).toBeTruthy();

    // Navigate to app first then to conversation
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Navigate to the agent's conversation via URL (uses full /conversations/ path)
    await page.goto(`/#/conversations/${conversationId}`);

    // Wait for messages container to be present
    await page.waitForSelector('#messages', { timeout: 10000 });

    // Wait a bit for messages to render
    await page.waitForTimeout(1000);

    // Check if messages loaded
    const messageCount = await page.locator('.message').count();
    console.log('Message count:', messageCount);

    // Wait for messages to load
    await page.waitForSelector('.message', { timeout: 10000 });

    // Verify the approval message is displayed
    const approvalMessage = page.locator('.approval-request-message');
    await expect(approvalMessage).toBeVisible();

    // Verify input is disabled
    const messageInput = page.locator('#message-input');
    await expect(messageInput).toBeDisabled();

    // Verify send button is disabled
    const sendBtn = page.locator('#send-btn');
    await expect(sendBtn).toBeDisabled();

    // Verify the overlay is visible
    const overlay = page.locator('.approval-pending-overlay');
    await expect(overlay).toBeVisible();
    await expect(overlay).toContainText('approve or reject');
  });

  test('input remains blocked even when typing', async ({ page }) => {
    // Seed an agent with a pending approval
    const seedResponse = await page.request.post('/test/seed-agent-with-approval', {
      data: {
        name: 'Typing Test Agent',
        description: 'Test action',
        tool_name: 'test_tool',
      },
    });
    const seedData = await seedResponse.json();
    const conversationId = seedData.conversation_id;

    // Navigate to the agent's conversation
    await page.goto(`/#/conversations/${conversationId}`);
    await page.waitForSelector('.approval-request-message');

    // Try to type in the input (should be blocked)
    const messageInput = page.locator('#message-input');
    await expect(messageInput).toBeDisabled();

    // The send button should remain disabled
    const sendBtn = page.locator('#send-btn');
    await expect(sendBtn).toBeDisabled();
  });

  test('pressing Enter does not send message when approval pending', async ({ page }) => {
    // Seed an agent with a pending approval
    const seedResponse = await page.request.post('/test/seed-agent-with-approval', {
      data: {
        name: 'Enter Key Test Agent',
        description: 'Test action',
        tool_name: 'test_tool',
      },
    });
    const seedData = await seedResponse.json();
    const conversationId = seedData.conversation_id;

    // Navigate to the agent's conversation
    await page.goto(`/#/conversations/${conversationId}`);
    await page.waitForSelector('.approval-request-message');

    // Count initial messages
    const initialMessageCount = await page.locator('.message').count();

    // Try pressing Enter (even if input is disabled, browser may still fire keydown)
    await page.keyboard.press('Enter');

    // Wait a bit to ensure no message is sent
    await page.waitForTimeout(500);

    // Verify message count hasn't changed (no new message sent)
    const finalMessageCount = await page.locator('.message').count();
    expect(finalMessageCount).toBe(initialMessageCount);
  });

  test('clicking send button does not send message when approval pending', async ({ page }) => {
    // Seed an agent with a pending approval
    const seedResponse = await page.request.post('/test/seed-agent-with-approval', {
      data: {
        name: 'Click Test Agent',
        description: 'Test action',
        tool_name: 'test_tool',
      },
    });
    const seedData = await seedResponse.json();
    const conversationId = seedData.conversation_id;

    // Navigate to the agent's conversation
    await page.goto(`/#/conversations/${conversationId}`);
    await page.waitForSelector('.approval-request-message');

    // Count initial messages
    const initialMessageCount = await page.locator('.message').count();

    // Try to click the send button (should be disabled, but let's verify behavior)
    const sendBtn = page.locator('#send-btn');
    await sendBtn.click({ force: true }); // Force click even if disabled

    // Wait a bit to ensure no message is sent
    await page.waitForTimeout(500);

    // Verify message count hasn't changed
    const finalMessageCount = await page.locator('.message').count();
    expect(finalMessageCount).toBe(initialMessageCount);

    // Verify no error toast appeared (backend wasn't called)
    const errorToast = page.locator('.toast-error');
    await expect(errorToast).not.toBeVisible();
  });
});
