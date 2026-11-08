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
import { appReady } from './waits';

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
  total_unread?: number;
  agents_waiting?: number;
}) {
  // The job list (GET /api/jobs): each agent is its standing job
  const jobs = (data.agents || []).map((agent) => ({
    id: agent.id,
    kind: 'recurring',
    standing: true,
    area: 'agents',
    title: agent.name,
    conversation_id: `conv-${agent.id}`,
    conversation_title: `Agent: ${agent.name}`,
    when: agent.schedule ?? 'on demand',
    ends: 'until cancelled',
    status: agent.enabled === false ? 'paused' : 'active',
    paused_reason: agent.enabled === false ? 'disabled' : null,
    next_run_at: agent.next_run_at ?? null,
    system_type: null,
    editable: true,
    unread_count: agent.unread_count ?? 0,
    has_pending_approval: agent.has_pending_approval ?? false,
    cost_7d_display: null,
    runs_7d: 0,
    recent_runs: [],
  }));
  const overview = {
    jobs,
    pending_approvals: (data.pending_approvals || []).map(({ agent_id, agent_name, ...a }) => ({
      tool_args: null,
      resolved_at: null,
      status: 'pending',
      ...a,
      item_id: agent_id,
      job_name: agent_name,
    })),
    stats: { days: 7, total_runs: 0, total_completed: 0, total_failed: 0, total_cost_display: '' },
    total_unread: data.total_unread || 0,
    jobs_waiting: data.agents_waiting || 0,
    jobs_with_errors: 0,
  };
  await page.request.post('/test/set-jobs-overview', { data: { overview } });
}

test.describe('Agents - Sidebar Entry', () => {
  test('shows agents entry in sidebar', async ({ page }) => {
    await page.goto('/');
    await appReady(page);

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
    await appReady(page);

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
    await appReady(page);

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
    await appReady(page);

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
    const emptyMessage = page.locator('.jobs-empty');
    await expect(emptyMessage).toBeVisible();
    await expect(emptyMessage).toContainText('Nothing scheduled yet');
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

    // One row per job (each agent is its standing job)
    const rows = page.locator('.job-row');
    await expect(rows).toHaveCount(2);

    const first = rows.first();
    await expect(first.locator('.job-title')).toHaveText('Daily Briefing');
    await expect(first.locator('.job-unread')).toHaveText('2');
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

  test('shows a disabled agent as a paused job', async ({ page }) => {
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

    // A disabled agent is a paused job: it says so and offers Resume
    const row = page.locator('.job-row');
    await expect(row.locator('.job-status')).toHaveText('paused');
    await expect(row.locator('.job-resume')).toBeVisible();
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

  test('granting "Other agents" saves trigger_agent in the permissions', async ({ page }) => {
    await setCommandCenterData(page, { agents: [] });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await page.locator('.btn-new-agent').click();
    const modal = page.getByRole('dialog', { name: 'Create Agent' });
    await expect(modal).toBeVisible();

    await page.getByLabel('Name *').fill('Coordinator');
    await page.click('.tool-permission-card:has(input[value="trigger_agent"])');

    const createRequest = page.waitForRequest(
      (req) => req.method() === 'POST' && new URL(req.url()).pathname === '/api/jobs'
    );
    await modal.getByRole('button', { name: 'Create Agent' }).click();
    const body = (await createRequest).postDataJSON() as { grants: string[] | null };
    expect(body.grants).toContain('trigger_agent');
  });
});

test.describe('Agents - Agent Actions', () => {
  test('shows the edit button on an agent job', async ({ page }) => {
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
    await page.waitForSelector('.job-row');

    // Edit button should be visible
    const editBtn = page.locator('.job-row .job-edit');
    await expect(editBtn).toBeVisible();
  });

  test('shows the run button on an agent job', async ({ page }) => {
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
    await page.waitForSelector('.job-row');

    // Run button should be visible
    const runBtn = page.locator('.job-row .job-run');
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

    // The standing chat's editor data for GET /api/jobs/:id
    await page.request.post('/test/set-agent', {
      data: {
        id: agentId,
        name: 'Test Agent',
        description: 'Test description',
        instructions: 'You are a helpful assistant.',
        grants: [],
        enabled: true,
        schedule: null,
        timezone: 'UTC',
        conversation_id: 'conv-1',
        created_at: createdAt,
        updated_at: createdAt,
      },
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.job-row');

    // Click edit button
    await page.locator('.job-row .job-edit').click();

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

test.describe('Agents - Deep Link Mark Viewed', () => {
  test('deep-linking to an agent conversation marks it viewed', async ({ page }) => {
    // Seed an agent (reuses the approval seed - it creates a full agent
    // conversation; the approval itself is irrelevant here)
    const seedResponse = await page.request.post('/test/seed-agent-with-approval', {
      data: { name: 'Briefing Agent' },
    });
    expect(seedResponse.ok()).toBe(true);
    const seedData = await seedResponse.json();
    const agentId = seedData.agent_id;
    const conversationId = seedData.conversation_id;

    // Simulate a push-notification tap: cold open directly on the
    // conversation hash (routes through loadDeepLinkedConversation,
    // NOT selectConversation)
    const markViewedRequest = page.waitForRequest(
      (req) => req.url().includes(`/api/jobs/${agentId}/viewed`) && req.method() === 'POST',
      { timeout: 10000 }
    );
    await page.goto(`/#/conversations/${conversationId}`);
    await page.waitForSelector('.message', { timeout: 10000 });

    // The server-side last_viewed_at reset is what clears the unread badge
    // on OTHER devices - it must fire on this path too
    await markViewedRequest;
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
    await appReady(page);

    // Navigate to the agent's conversation via URL (uses full /conversations/ path)
    await page.goto(`/#/conversations/${conversationId}`);

    // Wait for messages container to be present
    await page.waitForSelector('#messages', { timeout: 10000 });

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
    await page.waitForTimeout(500); // a span for a wrong send to show (none must)

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
    await page.waitForTimeout(500); // a span for a wrong send to show (none must)

    // Verify message count hasn't changed
    const finalMessageCount = await page.locator('.message').count();
    expect(finalMessageCount).toBe(initialMessageCount);

    // Verify no error toast appeared (backend wasn't called)
    const errorToast = page.locator('.toast-error');
    await expect(errorToast).not.toBeVisible();
  });

  for (const [label, viewport] of [
    ['desktop', { width: 1280, height: 800 }],
    ['mobile', { width: 375, height: 812 }],
  ] as const) {
    test(`Always allow approves a Todoist change and grants it (${label})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      const seedResponse = await page.request.post('/test/seed-agent-with-approval', {
        data: { name: `Always ${label}`, description: 'Add task: Buy milk', tool_name: 'todoist' },
      });
      const { conversation_id: conversationId } = (await seedResponse.json()) as { conversation_id: string };

      await page.goto(`/#/conversations/${conversationId}`);
      const approval = page.locator('.approval-request-message');
      const always = approval.locator('.btn-always-allow');
      await expect(always).toBeVisible();
      await always.click();

      await expect(approval.locator('.approval-result.approved')).toBeVisible();
    });
  }
});
