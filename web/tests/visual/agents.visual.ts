/**
 * Visual regression tests for Agents (Command Center) feature
 */
import { test, expect } from '../global-setup';

test.describe('Visual: Agents Sidebar Entry', () => {
  test('agents entry default state', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.agents-entry');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('agents-entry-default.png');
  });

  test('agents entry hover state', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.agents-entry');

    await page.locator('.agents-entry').hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.sidebar')).toHaveScreenshot('agents-entry-hover.png');
  });

  test('agents entry active state', async ({ page }) => {
    await page.goto('/#/agents');
    await page.waitForSelector('.agents-entry.active');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('agents-entry-active.png');
  });

  test('agents entry with badge', async ({ page }) => {
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [],
          agents: [
            {
              id: 'agent-1',
              name: 'Daily Brief',
              schedule: '0 9 * * *',
              timezone: 'America/New_York',
              enabled: true,
              tool_permissions: ['web_search', 'todoist'],
              conversation_id: 'conv-1',
              has_pending_approval: false,
              unread_count: 3,
            },
          ],
          recent_executions: [],
          total_unread: 3,
          agents_waiting: 0,
        },
      },
    });

    await page.goto('/');
    await page.waitForSelector('.agents-entry');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('agents-entry-with-badge.png');
  });

  test('agents entry with waiting indicator', async ({ page }) => {
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [
            {
              id: 'approval-1',
              agent_id: 'agent-1',
              agent_name: 'Research Agent',
              tool_name: 'todoist',
              tool_args: { operation: 'add_task', content: 'Test task' },
              description: 'Create Todoist task "Test task"',
              created_at: new Date().toISOString(),
            },
          ],
          agents: [
            {
              id: 'agent-1',
              name: 'Research Agent',
              schedule: '0 * * * *',
              timezone: 'UTC',
              enabled: true,
              tool_permissions: ['web_search', 'todoist'],
              conversation_id: 'conv-1',
              has_pending_approval: true,
              unread_count: 0,
            },
          ],
          recent_executions: [],
          total_unread: 0,
          agents_waiting: 1,
        },
      },
    });

    await page.goto('/');
    await page.waitForSelector('.agents-entry');
    await page.waitForTimeout(500); // Wait for animation

    await expect(page.locator('.sidebar')).toHaveScreenshot('agents-entry-with-waiting.png');
  });

  test('planner and agents side by side with badges', async ({ page }) => {
    // Mock Todoist as connected so planner shows
    await page.route('**/auth/todoist/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ connected: true }),
      });
    });

    // Set command center data with badges
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [
            {
              id: 'approval-1',
              agent_id: 'agent-1',
              agent_name: 'Test Agent',
              tool_name: 'todoist',
              tool_args: { operation: 'add_task', content: 'Test' },
              description: 'Create task',
              created_at: new Date().toISOString(),
            },
          ],
          agents: [
            {
              id: 'agent-1',
              name: 'Test Agent',
              schedule: '0 9 * * *',
              timezone: 'UTC',
              enabled: true,
              tool_permissions: ['todoist'],
              conversation_id: 'conv-1',
              has_pending_approval: true,
              unread_count: 5,
            },
          ],
          recent_executions: [],
          total_unread: 5,
          agents_waiting: 1,
        },
      },
    });

    await page.goto('/');
    await page.waitForSelector('.planner-entry');
    await page.waitForSelector('.agents-entry');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('sidebar-nav-row-with-badges.png');
  });
});

test.describe('Visual: Command Center - Desktop', () => {
  test('empty command center', async ({ page }) => {
    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('command-center-empty.png');
  });

  test('command center with agents', async ({ page }) => {
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [],
          agents: [
            {
              id: 'agent-1',
              name: 'Daily Briefing',
              description: 'Summarizes your schedule each morning',
              schedule: '0 9 * * *',
              timezone: 'America/New_York',
              enabled: true,
              tool_permissions: ['web_search', 'todoist', 'google_calendar'],
              conversation_id: 'conv-1',
              last_run_at: new Date(Date.now() - 3600000).toISOString(),
              next_run_at: new Date(Date.now() + 3600000).toISOString(),
              has_pending_approval: false,
              unread_count: 2,
            },
            {
              id: 'agent-2',
              name: 'Research Assistant',
              description: 'Finds relevant articles',
              schedule: '0 */2 * * *',
              timezone: 'UTC',
              enabled: true,
              tool_permissions: ['web_search', 'fetch_url'],
              conversation_id: 'conv-2',
              has_pending_approval: false,
              unread_count: 0,
            },
            {
              id: 'agent-3',
              name: 'Social Monitor',
              description: 'Monitors social media',
              schedule: null,
              timezone: 'UTC',
              enabled: false,
              tool_permissions: ['web_search'],
              conversation_id: 'conv-3',
              has_pending_approval: false,
              unread_count: 0,
            },
          ],
          recent_executions: [
            {
              id: 'exec-1',
              agent_id: 'agent-1',
              agent_name: 'Daily Briefing',
              status: 'completed',
              trigger_type: 'scheduled',
              started_at: new Date(Date.now() - 3600000).toISOString(),
              completed_at: new Date(Date.now() - 3500000).toISOString(),
            },
            {
              id: 'exec-2',
              agent_id: 'agent-2',
              agent_name: 'Research Assistant',
              status: 'completed',
              trigger_type: 'manual',
              started_at: new Date(Date.now() - 7200000).toISOString(),
              completed_at: new Date(Date.now() - 7100000).toISOString(),
            },
          ],
          total_unread: 2,
          agents_waiting: 0,
        },
      },
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('command-center-with-agents.png');
  });

  test('command center with pending approvals', async ({ page }) => {
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [
            {
              id: 'approval-1',
              agent_id: 'agent-1',
              agent_name: 'Research Agent',
              tool_name: 'todoist',
              tool_args: { operation: 'add_task', content: 'Review quarterly report' },
              description: 'Create Todoist task "Review quarterly report"',
              created_at: new Date(Date.now() - 1800000).toISOString(),
            },
            {
              id: 'approval-2',
              agent_id: 'agent-2',
              agent_name: 'Social Agent',
              tool_name: 'execute_code',
              tool_args: { code: 'print("Hello")' },
              description: 'Execute code: print("Hello")',
              created_at: new Date(Date.now() - 3600000).toISOString(),
            },
          ],
          agents: [
            {
              id: 'agent-1',
              name: 'Research Agent',
              schedule: '0 * * * *',
              timezone: 'UTC',
              enabled: true,
              tool_permissions: ['web_search', 'todoist'],
              conversation_id: 'conv-1',
              has_pending_approval: true,
              unread_count: 1,
            },
            {
              id: 'agent-2',
              name: 'Social Agent',
              schedule: '0 12 * * *',
              timezone: 'America/Los_Angeles',
              enabled: true,
              tool_permissions: ['web_search', 'execute_code'],
              conversation_id: 'conv-2',
              has_pending_approval: true,
              unread_count: 0,
            },
          ],
          recent_executions: [],
          total_unread: 1,
          agents_waiting: 2,
        },
      },
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await page.waitForSelector('.approval-card');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('command-center-with-approvals.png');
  });

  test('command center loading state', async ({ page }) => {
    // Set a delay on the response
    await page.route('**/api/agents/command-center', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      await route.continue();
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center-loading');

    await expect(page.locator('.main')).toHaveScreenshot('command-center-loading.png');
  });
});

test.describe('Visual: Command Center - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('command center mobile view', async ({ page }) => {
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [
            {
              id: 'approval-1',
              agent_id: 'agent-1',
              agent_name: 'Research Agent',
              tool_name: 'todoist',
              tool_args: { operation: 'add_task', content: 'Test task' },
              description: 'Create Todoist task "Test task"',
              created_at: new Date().toISOString(),
            },
          ],
          agents: [
            {
              id: 'agent-1',
              name: 'Daily Briefing',
              schedule: '0 9 * * *',
              timezone: 'UTC',
              enabled: true,
              tool_permissions: ['web_search'],
              conversation_id: 'conv-1',
              has_pending_approval: true,
              unread_count: 2,
            },
            {
              id: 'agent-2',
              name: 'Research Assistant',
              schedule: '0 * * * *',
              timezone: 'UTC',
              enabled: true,
              tool_permissions: ['web_search'],
              conversation_id: 'conv-2',
              has_pending_approval: false,
              unread_count: 0,
            },
          ],
          recent_executions: [],
          total_unread: 2,
          agents_waiting: 1,
        },
      },
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('command-center-mobile.png');
  });
});

test.describe('Visual: Agent Trigger Messages', () => {
  test('manual trigger message', async ({ page }) => {
    // Seed a conversation with a trigger message
    await page.request.post('/test/seed', {
      data: {
        conversations: [
          {
            title: 'Agent: Daily Briefing',
            messages: [
              {
                role: 'user',
                content: '[Manual trigger at 2026-01-15 09:00 UTC]',
              },
              {
                role: 'assistant',
                content: 'Good morning! Here is your daily briefing...',
              },
            ],
          },
        ],
      },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click on the seeded conversation
    const convItem = page.locator('.conversation-item').first();
    await convItem.click();
    await page.waitForSelector('.message.trigger-message');
    await page.waitForTimeout(300);

    await expect(page.locator('#messages')).toHaveScreenshot('trigger-message-manual.png');
  });

  test('scheduled trigger message', async ({ page }) => {
    // Seed a conversation with a scheduled trigger message
    await page.request.post('/test/seed', {
      data: {
        conversations: [
          {
            title: 'Agent: Research Assistant',
            messages: [
              {
                role: 'user',
                content: '[Scheduled run at 2026-01-15 14:00 UTC]',
              },
              {
                role: 'assistant',
                content: 'I found some relevant articles for you...',
              },
            ],
          },
        ],
      },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click on the seeded conversation
    const convItem = page.locator('.conversation-item').first();
    await convItem.click();
    await page.waitForSelector('.message.trigger-message');
    await page.waitForTimeout(300);

    await expect(page.locator('#messages')).toHaveScreenshot('trigger-message-scheduled.png');
  });

  test('agent chain trigger message', async ({ page }) => {
    // Seed a conversation with an agent chain trigger message
    await page.request.post('/test/seed', {
      data: {
        conversations: [
          {
            title: 'Agent: Follow-up Agent',
            messages: [
              {
                role: 'user',
                content: '[Triggered by another agent at 2026-01-15 16:30 UTC]',
              },
              {
                role: 'assistant',
                content: 'Following up on the previous analysis...',
              },
            ],
          },
        ],
      },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click on the seeded conversation
    const convItem = page.locator('.conversation-item').first();
    await convItem.click();
    await page.waitForSelector('.message.trigger-message');
    await page.waitForTimeout(300);

    await expect(page.locator('#messages')).toHaveScreenshot('trigger-message-agent-chain.png');
  });

  test('multiple trigger messages in conversation', async ({ page }) => {
    // Seed a conversation with multiple trigger messages
    await page.request.post('/test/seed', {
      data: {
        conversations: [
          {
            title: 'Agent: Daily Briefing',
            messages: [
              {
                role: 'user',
                content: '[Scheduled run at 2026-01-14 09:00 UTC]',
              },
              {
                role: 'assistant',
                content: 'Good morning! Here is yesterday\'s briefing.',
              },
              {
                role: 'user',
                content: '[Scheduled run at 2026-01-15 09:00 UTC]',
              },
              {
                role: 'assistant',
                content: 'Good morning! Here is today\'s briefing.',
              },
            ],
          },
        ],
      },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click on the seeded conversation
    const convItem = page.locator('.conversation-item').first();
    await convItem.click();
    await page.waitForSelector('.message.trigger-message');
    await page.waitForTimeout(300);

    await expect(page.locator('#messages')).toHaveScreenshot('trigger-messages-multiple.png');
  });
});

test.describe('Visual: Agent Editor Modal', () => {
  test('new agent editor', async ({ page }) => {
    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Click the new agent button
    await page.click('.btn-new-agent');
    await page.waitForSelector('.agent-editor');
    await page.waitForTimeout(300);

    await expect(page.locator('.agent-editor-modal')).toHaveScreenshot('agent-editor-new.png');
  });

  test('agent editor with data', async ({ page }) => {
    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Click the new agent button
    await page.click('.btn-new-agent');
    await page.waitForSelector('.agent-editor');

    // Fill in the form (just basic fields for visual test)
    await page.fill('#agent-name', 'My Test Agent');
    await page.fill('#agent-description', 'This agent helps with testing');
    // Select a schedule preset chip
    await page.click('.schedule-preset-chip[data-cron="0 9 * * *"]');
    await page.fill('#agent-system-prompt', 'You are a helpful testing assistant.');

    await page.waitForTimeout(200);

    await expect(page.locator('.agent-editor-modal')).toHaveScreenshot('agent-editor-filled.png');
  });

  test('agent editor tool permissions section', async ({ page }) => {
    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    // Click the new agent button
    await page.click('.btn-new-agent');
    await page.waitForSelector('.agent-editor');

    // Fill in name
    await page.fill('#agent-name', 'Test Agent');

    // Scroll to the tool permissions section within the modal body
    const modalBody = page.locator('.agent-editor-body');
    await modalBody.evaluate((el) => el.scrollTo(0, el.scrollHeight));

    await page.waitForTimeout(200);

    // Click on the tool permission cards (labels) to toggle them
    await page.click('.tool-permission-card:has(input[value="todoist"])');
    await page.click('.tool-permission-card:has(input[value="google_calendar"])');
    // WhatsApp is only shown when configured - click if available
    const whatsappCard = page.locator('.tool-permission-card:has(input[value="whatsapp"])');
    if (await whatsappCard.count() > 0) {
      await whatsappCard.click();
    }

    await page.waitForTimeout(200);

    await expect(page.locator('.agent-editor-modal')).toHaveScreenshot('agent-editor-tool-permissions.png');
  });

  test('agent editor in edit mode with delete button', async ({ page }) => {
    const mockAgent = {
      id: 'test-agent-1',
      name: 'Test Agent for Edit',
      description: 'Agent to test edit mode',
      system_prompt: 'You are a test agent.',
      schedule: '0 9 * * *',
      timezone: 'UTC',
      enabled: true,
      tool_permissions: ['todoist', 'google_calendar', 'whatsapp'],
      model: 'gemini-3-flash-preview',
      conversation_id: null,
      last_run_at: null,
      next_run_at: null,
      created_at: '2026-01-17T10:00:00Z',
      updated_at: '2026-01-17T10:00:00Z',
      has_pending_approval: false,
      unread_count: 0,
      last_execution_status: null,
    };

    // Set up a mock agent via test endpoint
    await page.request.post('/test/set-agents-command-center', {
      data: {
        command_center: {
          pending_approvals: [],
          agents: [mockAgent],
          recent_executions: [],
          total_unread: 0,
          agents_waiting: 0,
        },
      },
    });

    // Mock the individual agent fetch endpoint
    await page.route('**/api/agents/test-agent-1', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockAgent),
      });
    });

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await page.waitForSelector('.agent-card');

    // Click on the agent card to open editor in edit mode
    await page.click('.agent-card[data-agent-id="test-agent-1"] .btn-edit');
    await page.waitForSelector('.agent-editor');
    await page.waitForTimeout(300);

    // Verify delete button is visible
    await expect(page.locator('.agent-editor-delete')).toBeVisible();

    await expect(page.locator('.agent-editor-modal')).toHaveScreenshot('agent-editor-edit-mode.png');
  });
});
