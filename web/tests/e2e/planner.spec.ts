/**
 * E2E tests for Planner feature
 */
import { test, expect } from '../global-setup';

test.describe('Planner - Sidebar Entry Visibility', () => {
  test('shows planner entry when todoist connected', async ({ page }) => {
    // Set todoist as connected
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: false },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Planner entry should be visible in sidebar
    const plannerEntry = page.locator('.planner-entry');
    await expect(plannerEntry).toBeVisible();
    await expect(plannerEntry).toContainText('Planner');
  });

  test('shows planner entry when calendar connected', async ({ page }) => {
    // Set calendar as connected
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: false, calendar: true },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Planner entry should be visible in sidebar
    const plannerEntry = page.locator('.planner-entry');
    await expect(plannerEntry).toBeVisible();
  });

  test('shows planner entry when both integrations connected', async ({ page }) => {
    // Set both as connected
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Planner entry should be visible in sidebar
    const plannerEntry = page.locator('.planner-entry');
    await expect(plannerEntry).toBeVisible();
  });

  test('hides planner entry when no integrations connected', async ({ page }) => {
    // Set both as disconnected
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: false, calendar: false },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Planner entry should NOT be visible
    const plannerEntry = page.locator('.planner-entry');
    await expect(plannerEntry).not.toBeVisible();
  });
});

test.describe('Planner - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    // Enable planner by connecting todoist
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('navigates to planner via sidebar click', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click the planner entry
    const plannerEntry = page.locator('.planner-entry');
    await plannerEntry.click();

    // Should show planner dashboard
    const plannerDashboard = page.locator('#planner-dashboard');
    await expect(plannerDashboard).toBeVisible();

    // Should have dashboard header with title
    const dashboardTitle = page.locator('.dashboard-title');
    await expect(dashboardTitle).toContainText('Your Schedule');

    // URL should be updated
    await expect(page).toHaveURL(/#\/planner$/);
  });

  test('navigates to planner via deep link', async ({ page }) => {
    // Enable planner first
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: false },
    });

    // Navigate directly to planner route
    await page.goto('/#/planner');

    // Should show planner dashboard
    const plannerDashboard = page.locator('#planner-dashboard');
    await expect(plannerDashboard).toBeVisible({ timeout: 10000 });
  });

  test('browser back from planner returns to previous view', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant');

    // Navigate to planner
    const plannerEntry = page.locator('.planner-entry');
    await plannerEntry.click();
    await expect(page.locator('#planner-dashboard')).toBeVisible();

    // Go back
    await page.goBack();

    // Should be back on the conversation
    await expect(page.locator('#messages')).toBeVisible();
  });

  test('planner entry has active state when on planner view', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click the planner entry
    const plannerEntry = page.locator('.planner-entry');
    await plannerEntry.click();

    // Entry should have active class
    await expect(plannerEntry).toHaveClass(/active/);
  });
});

test.describe('Planner - Dashboard Display', () => {
  test.beforeEach(async ({ page }) => {
    // Enable planner with both integrations
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('displays dashboard with events and tasks', async ({ page }) => {
    await page.goto('/#/planner');

    // Wait for dashboard to load
    const dashboard = page.locator('#planner-dashboard');
    await expect(dashboard).toBeVisible();

    // Should show Today section
    const todaySection = page.locator('.dashboard-day').first();
    await expect(todaySection).toContainText('Today');

    // Should show events section (from mock data)
    await expect(dashboard).toContainText('Events');

    // Should show tasks section (from mock data)
    await expect(dashboard).toContainText('Tasks');
  });

  test('displays overdue tasks section when present', async ({ page }) => {
    await page.goto('/#/planner');

    // Wait for dashboard to load
    const dashboard = page.locator('#planner-dashboard');
    await expect(dashboard).toBeVisible();

    // Should show overdue section (mock data has one overdue task when todoist connected)
    const overdueSection = page.locator('.dashboard-section.overdue');
    await expect(overdueSection).toBeVisible();
    await expect(overdueSection).toContainText('Overdue');
  });

  test('shows dashboard with partial integrations', async ({ page }) => {
    // Connect only calendar (todoist disconnected)
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: false, calendar: true },
    });

    await page.goto('/#/planner');

    // Should show dashboard even with one integration disconnected
    const dashboard = page.locator('#planner-dashboard');
    await expect(dashboard).toBeVisible();

    // Should show events from calendar
    await expect(dashboard).toContainText('Events');

    // Should show days sections
    await expect(dashboard.locator('.dashboard-day').first()).toBeVisible();
  });
});

test.describe('Planner - Actions', () => {
  test.beforeEach(async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('refresh button triggers dashboard reload', async ({ page }) => {
    await page.goto('/#/planner');

    // Wait for initial dashboard load
    await expect(page.locator('#planner-dashboard')).toBeVisible();
    await expect(page.locator('.dashboard-day').first()).toBeVisible();

    // Click refresh
    const refreshBtn = page.locator('.planner-refresh-btn');
    await refreshBtn.click();

    // Should show loading state briefly or just update (mock is fast)
    // Verify dashboard is still visible after refresh
    await expect(page.locator('.dashboard-day').first()).toBeVisible();
  });

  test('reset button resets conversation', async ({ page }) => {
    await page.goto('/#/planner');

    // Wait for dashboard to load
    await expect(page.locator('#planner-dashboard')).toBeVisible();

    // Click reset button
    const resetBtn = page.locator('.planner-reset-btn');
    await resetBtn.click();

    // Dashboard should still be visible after reset
    await expect(page.locator('#planner-dashboard')).toBeVisible();
  });
});

test.describe('Planner - Week Section', () => {
  test.beforeEach(async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('week section is collapsible', async ({ page }) => {
    await page.goto('/#/planner');

    // Wait for dashboard to load
    await expect(page.locator('#planner-dashboard')).toBeVisible();

    // Find the "This Week" details element
    const weekSection = page.locator('.dashboard-section details');
    const summary = weekSection.locator('summary');

    // Should show week summary
    await expect(summary).toContainText('This Week');

    // Click to expand/collapse (default is collapsed)
    if (await weekSection.evaluate((el) => !(el as HTMLDetailsElement).open)) {
      await summary.click();
      // Should be expanded now
      await expect(weekSection).toHaveAttribute('open', '');
    }
  });
});

test.describe('Planner - Copy to Clipboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('can copy event item to clipboard', async ({ page, browserName }) => {
    test.skip(browserName === 'webkit', 'Webkit does not support clipboard permissions');

    // Grant clipboard permissions (only runs on non-webkit browsers)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);

    await page.goto('/#/planner');

    // Wait for dashboard to load
    await expect(page.locator('.planner-item').first()).toBeVisible();

    // Hover over an event item to reveal copy button
    const eventItem = page.locator('.planner-item').first();
    await eventItem.hover();

    // Click copy button
    const copyBtn = eventItem.locator('.planner-item-copy');
    await copyBtn.click();

    // Button should show checkmark briefly
    await expect(copyBtn).toHaveClass(/copied/);

    // Verify clipboard content (event should have summary)
    const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboardText).toBeTruthy();
  });
});

test.describe('Planner - Empty States', () => {
  test('shows empty state when no events or tasks', async ({ page }) => {
    // Set custom empty dashboard
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: false, calendar: false },
    });

    // This test won't run because planner entry is hidden when no integrations
    // Instead, test with integrations but empty data
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            { date: '2025-01-11', day_name: 'Today', events: [], tasks: [] },
            { date: '2025-01-12', day_name: 'Tomorrow', events: [], tasks: [] },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: null,
          calendar_error: null,
          server_time: new Date().toISOString(),
        },
      },
    });

    await page.goto('/#/planner');

    // Wait for dashboard to load
    await expect(page.locator('#planner-dashboard')).toBeVisible();

    // Should show "No events or tasks" message in day sections
    await expect(page.locator('.dashboard-empty')).toBeVisible();
  });
});

test.describe('Planner - Error States', () => {
  test('shows error message when integration has error', async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    // Set dashboard with error
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: 'Token expired',
          calendar_error: null,
          server_time: new Date().toISOString(),
        },
      },
    });

    await page.goto('/#/planner');

    // Should show error message
    const errorMsg = page.locator('.dashboard-error');
    await expect(errorMsg).toBeVisible();
    await expect(errorMsg).toContainText('Todoist');
    await expect(errorMsg).toContainText('Token expired');
  });
});

test.describe('Planner - Calendar Labels', () => {
  test.beforeEach(async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('shows calendar labels on non-primary calendar events', async ({ page }) => {
    // Enable planner first
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    // Use current date to avoid past date filtering issues
    const today = new Date().toISOString().split('T')[0];

    // Set dashboard with events from multiple calendars
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: today,
              day_name: 'Today',
              events: [
                {
                  id: '1',
                  summary: 'Primary Calendar Event',
                  start: `${today}T10:00:00Z`,
                  end: `${today}T11:00:00Z`,
                  is_all_day: false,
                  calendar_id: 'primary',
                  calendar_summary: 'My Calendar',
                },
                {
                  id: '2',
                  summary: 'Work Calendar Event',
                  start: `${today}T14:00:00Z`,
                  end: `${today}T15:00:00Z`,
                  is_all_day: false,
                  calendar_id: 'work@example.com',
                  calendar_summary: 'Work Calendar',
                },
                {
                  id: '3',
                  summary: 'Family Calendar Event',
                  start: `${today}T16:00:00Z`,
                  end: `${today}T17:00:00Z`,
                  is_all_day: false,
                  calendar_id: 'family@example.com',
                  calendar_summary: 'Family',
                },
              ],
              tasks: [],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: null,
          calendar_error: null,
          server_time: new Date().toISOString(),
        },
      },
    });

    await page.goto('/#/planner');
    await expect(page.locator('#planner-dashboard')).toBeVisible();

    // Wait for dashboard to load events
    await page.waitForLoadState('networkidle');

    // Get all event items
    const events = page.locator('.planner-item-event');
    await expect(events).toHaveCount(3, { timeout: 10000 });

    // Primary calendar event should NOT have a calendar label
    const primaryEvent = events.first();
    await expect(primaryEvent).toContainText('Primary Calendar Event');
    await expect(primaryEvent.locator('.planner-item-calendar')).not.toBeVisible();

    // Work calendar event should have a calendar label
    const workEvent = events.nth(1);
    await expect(workEvent).toContainText('Work Calendar Event');
    const workLabel = workEvent.locator('.planner-item-calendar');
    await expect(workLabel).toBeVisible();
    await expect(workLabel).toContainText('Work Calendar');

    // Family calendar event should have a calendar label
    const familyEvent = events.nth(2);
    await expect(familyEvent).toContainText('Family Calendar Event');
    const familyLabel = familyEvent.locator('.planner-item-calendar');
    await expect(familyLabel).toBeVisible();
    await expect(familyLabel).toContainText('Family');
  });

  test('primary calendar events have no label', async ({ page }) => {
    // Enable planner first
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    // Use current date to avoid past date filtering issues
    const today = new Date().toISOString().split('T')[0];

    // Set dashboard with only primary calendar events
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: today,
              day_name: 'Today',
              events: [
                {
                  id: '1',
                  summary: 'Event 1',
                  start: `${today}T10:00:00Z`,
                  end: `${today}T11:00:00Z`,
                  is_all_day: false,
                  calendar_id: 'primary',
                  calendar_summary: 'My Calendar',
                },
                {
                  id: '2',
                  summary: 'Event 2',
                  start: `${today}T14:00:00Z`,
                  end: `${today}T15:00:00Z`,
                  is_all_day: false,
                  calendar_id: 'primary',
                  calendar_summary: 'My Calendar',
                },
              ],
              tasks: [],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: null,
          calendar_error: null,
          server_time: new Date().toISOString(),
        },
      },
    });

    await page.goto('/#/planner');
    await expect(page.locator('#planner-dashboard')).toBeVisible();

    // Wait for dashboard to load events
    await page.waitForLoadState('networkidle');

    // None of the events should have calendar labels
    const calendarLabels = page.locator('.planner-item-calendar');
    await expect(calendarLabels).toHaveCount(0);
  });
});
