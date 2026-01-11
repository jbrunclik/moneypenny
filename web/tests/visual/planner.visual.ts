/**
 * Visual regression tests for Planner feature
 */
import { test, expect } from '../global-setup';

test.describe('Visual: Planner Sidebar Entry', () => {
  test('planner entry default state', async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    await page.goto('/');
    await page.waitForSelector('.planner-entry');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('planner-entry-default.png');
  });

  test('planner entry hover state', async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    await page.goto('/');
    await page.waitForSelector('.planner-entry');

    await page.locator('.planner-entry').hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.sidebar')).toHaveScreenshot('planner-entry-hover.png');
  });

  test('planner entry active state', async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.planner-entry.active');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('planner-entry-active.png');
  });
});

test.describe('Visual: Planner Dashboard - Desktop', () => {
  test.beforeEach(async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('dashboard full layout with multiple days', async ({ page }) => {
    // Set comprehensive dashboard data
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [
                {
                  id: 'event-1',
                  summary: 'Team Standup',
                  start: '2024-12-25T09:00:00',
                  end: '2024-12-25T09:30:00',
                  is_all_day: false,
                  location: 'Conference Room A',
                },
                {
                  id: 'event-2',
                  summary: 'Client Meeting',
                  start: '2024-12-25T14:00:00',
                  end: '2024-12-25T15:30:00',
                  is_all_day: false,
                  location: 'Zoom',
                },
              ],
              tasks: [
                {
                  id: 'task-1',
                  content: 'Review pull requests',
                  priority: 3,
                  project_name: 'Development',
                },
                {
                  id: 'task-2',
                  content: 'Update documentation',
                  priority: 2,
                  project_name: 'Development',
                },
              ],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [
                {
                  id: 'event-3',
                  summary: 'Project Review',
                  start: '2024-12-26T10:00:00',
                  end: '2024-12-26T11:00:00',
                  is_all_day: false,
                },
              ],
              tasks: [
                {
                  id: 'task-3',
                  content: 'Prepare presentation',
                  priority: 4,
                  project_name: 'Marketing',
                },
              ],
            },
            {
              date: '2024-12-27',
              day_name: 'Friday',
              events: [],
              tasks: [
                {
                  id: 'task-4',
                  content: 'Code review',
                  priority: 2,
                  project_name: 'Development',
                },
              ],
            },
            {
              date: '2024-12-28',
              day_name: 'Saturday',
              events: [
                {
                  id: 'event-4',
                  summary: 'Weekend Hiking Trip',
                  is_all_day: true,
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
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('#planner-dashboard');
    await page.waitForTimeout(500);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('dashboard-full.png');
  });

  test('dashboard with overdue tasks', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [],
              tasks: [
                {
                  id: 'task-1',
                  content: 'Regular task for today',
                  priority: 2,
                  project_name: 'Work',
                },
              ],
            },
          ],
          overdue_tasks: [
            {
              id: 'overdue-1',
              content: 'Critical bug fix',
              priority: 4,
              project_name: 'Production',
              due_string: 'Dec 20',
            },
            {
              id: 'overdue-2',
              content: 'Submit expense report',
              priority: 3,
              project_name: 'Admin',
              due_string: 'Dec 22',
            },
          ],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: null,
          calendar_error: null,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.dashboard-section.overdue');
    await page.waitForTimeout(500);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('dashboard-overdue.png');
  });

  test('dashboard error states', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: 'Failed to fetch tasks: Token expired',
          calendar_error: 'API rate limit exceeded',
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.dashboard-error');
    await page.waitForTimeout(300);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('dashboard-errors.png');
  });

  test('dashboard empty state', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [],
              tasks: [],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [],
              tasks: [],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          todoist_error: null,
          calendar_error: null,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.dashboard-empty');
    await page.waitForTimeout(300);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('dashboard-empty.png');
  });

  test('week section collapsed', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [],
              tasks: [{ id: 'task-1', content: 'Today task', priority: 2 }],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [],
              tasks: [{ id: 'task-2', content: 'Tomorrow task', priority: 2 }],
            },
            {
              date: '2024-12-27',
              day_name: 'Friday',
              events: [],
              tasks: [{ id: 'task-3', content: 'Friday task', priority: 2 }],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.dashboard-section details');
    await page.waitForTimeout(300);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('week-collapsed.png');
  });

  test('week section expanded', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [],
              tasks: [{ id: 'task-1', content: 'Today task', priority: 2 }],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [],
              tasks: [{ id: 'task-2', content: 'Tomorrow task', priority: 2 }],
            },
            {
              date: '2024-12-27',
              day_name: 'Friday',
              events: [],
              tasks: [{ id: 'task-3', content: 'Friday task', priority: 2 }],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.dashboard-section details');

    // Click to expand
    await page.locator('.dashboard-section details summary').click();
    await page.waitForTimeout(400); // Wait for expand animation

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('week-expanded.png');
  });

  test('planner item hover state', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [
                {
                  id: 'event-1',
                  summary: 'Team Standup',
                  start: '2024-12-25T09:00:00',
                  end: '2024-12-25T09:30:00',
                  is_all_day: false,
                },
                {
                  id: 'event-2',
                  summary: 'Client Presentation',
                  start: '2024-12-25T14:00:00',
                  end: '2024-12-25T15:30:00',
                  is_all_day: false,
                  location: 'Conference Room B',
                },
              ],
              tasks: [
                {
                  id: 'task-1',
                  content: 'Review pull requests',
                  priority: 3,
                  project_name: 'Development',
                },
                {
                  id: 'task-2',
                  content: 'Update documentation',
                  priority: 2,
                  project_name: 'Development',
                },
              ],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [
                {
                  id: 'event-3',
                  summary: 'Project Planning Session',
                  start: '2024-12-26T10:00:00',
                  end: '2024-12-26T11:30:00',
                  is_all_day: false,
                },
              ],
              tasks: [
                {
                  id: 'task-3',
                  content: 'Prepare Q1 budget',
                  priority: 4,
                  project_name: 'Finance',
                },
              ],
            },
            {
              date: '2024-12-27',
              day_name: 'Friday',
              events: [],
              tasks: [
                {
                  id: 'task-4',
                  content: 'Code review for feature-x',
                  priority: 2,
                  project_name: 'Development',
                },
                {
                  id: 'task-5',
                  content: 'Team retrospective prep',
                  priority: 1,
                  project_name: 'Management',
                },
              ],
            },
            {
              date: '2024-12-28',
              day_name: 'Saturday',
              events: [
                {
                  id: 'event-4',
                  summary: 'Family Brunch',
                  is_all_day: true,
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-29',
              day_name: 'Sunday',
              events: [],
              tasks: [
                {
                  id: 'task-6',
                  content: 'Weekly meal prep',
                  priority: 1,
                  project_name: 'Personal',
                },
              ],
            },
            {
              date: '2024-12-30',
              day_name: 'Monday',
              events: [
                {
                  id: 'event-5',
                  summary: 'Year-end Review Meeting',
                  start: '2024-12-30T13:00:00',
                  end: '2024-12-30T14:00:00',
                  is_all_day: false,
                },
              ],
              tasks: [
                {
                  id: 'task-7',
                  content: 'Submit expense reports',
                  priority: 3,
                  project_name: 'Admin',
                },
              ],
            },
            {
              date: '2024-12-31',
              day_name: 'Tuesday',
              events: [
                {
                  id: 'event-6',
                  summary: 'New Year\'s Eve Party',
                  start: '2024-12-31T20:00:00',
                  is_all_day: false,
                  location: 'Downtown',
                },
              ],
              tasks: [],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.planner-item');

    await page.locator('.planner-item').first().hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.dashboard-day').first()).toHaveScreenshot('item-hover.png');
  });

  test('priority indicators P2, P3, P4', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [],
              tasks: [
                {
                  id: 'task-1',
                  content: 'Low priority task (P1)',
                  priority: 1,
                  project_name: 'Work',
                },
                {
                  id: 'task-2',
                  content: 'Medium priority task (P2)',
                  priority: 2,
                  project_name: 'Work',
                },
                {
                  id: 'task-3',
                  content: 'High priority task (P3)',
                  priority: 3,
                  project_name: 'Work',
                },
                {
                  id: 'task-4',
                  content: 'Urgent task (P4)',
                  priority: 4,
                  project_name: 'Work',
                },
              ],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [],
              tasks: [
                {
                  id: 'task-5',
                  content: 'Review marketing materials',
                  priority: 2,
                  project_name: 'Marketing',
                },
              ],
            },
            {
              date: '2024-12-27',
              day_name: 'Friday',
              events: [],
              tasks: [
                {
                  id: 'task-6',
                  content: 'Plan sprint goals',
                  priority: 3,
                  project_name: 'Development',
                },
              ],
            },
            {
              date: '2024-12-28',
              day_name: 'Saturday',
              events: [],
              tasks: [
                {
                  id: 'task-7',
                  content: 'Grocery shopping',
                  priority: 1,
                  project_name: 'Personal',
                },
              ],
            },
            {
              date: '2024-12-29',
              day_name: 'Sunday',
              events: [],
              tasks: [
                {
                  id: 'task-8',
                  content: 'Prepare weekly report',
                  priority: 2,
                  project_name: 'Work',
                },
              ],
            },
            {
              date: '2024-12-30',
              day_name: 'Monday',
              events: [],
              tasks: [
                {
                  id: 'task-9',
                  content: 'Security audit follow-up',
                  priority: 4,
                  project_name: 'DevOps',
                },
              ],
            },
            {
              date: '2024-12-31',
              day_name: 'Tuesday',
              events: [],
              tasks: [
                {
                  id: 'task-10',
                  content: 'Year-end documentation',
                  priority: 3,
                  project_name: 'Admin',
                },
              ],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: false,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.planner-item');
    await page.waitForTimeout(300);

    await expect(page.locator('.dashboard-day').first()).toHaveScreenshot('priority-indicators.png');
  });

  test('all-day event styling', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [
                {
                  id: 'event-1',
                  summary: 'Christmas Holiday',
                  is_all_day: true,
                },
                {
                  id: 'event-2',
                  summary: 'Lunch with Family',
                  start: '2024-12-25T12:00:00',
                  end: '2024-12-25T13:30:00',
                  is_all_day: false,
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-26',
              day_name: 'Tomorrow',
              events: [
                {
                  id: 'event-3',
                  summary: 'Boxing Day Sales',
                  is_all_day: true,
                },
                {
                  id: 'event-4',
                  summary: 'Coffee with Sarah',
                  start: '2024-12-26T10:00:00',
                  end: '2024-12-26T11:00:00',
                  is_all_day: false,
                  location: 'Starbucks',
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-27',
              day_name: 'Friday',
              events: [
                {
                  id: 'event-5',
                  summary: 'Team Lunch',
                  start: '2024-12-27T12:30:00',
                  end: '2024-12-27T14:00:00',
                  is_all_day: false,
                  location: 'Italian Restaurant',
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-28',
              day_name: 'Saturday',
              events: [
                {
                  id: 'event-6',
                  summary: 'Weekend Getaway',
                  is_all_day: true,
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-29',
              day_name: 'Sunday',
              events: [
                {
                  id: 'event-7',
                  summary: 'Weekend Getaway (Day 2)',
                  is_all_day: true,
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-30',
              day_name: 'Monday',
              events: [
                {
                  id: 'event-8',
                  summary: 'Back to Work - Team Sync',
                  start: '2024-12-30T09:00:00',
                  end: '2024-12-30T10:00:00',
                  is_all_day: false,
                },
              ],
              tasks: [],
            },
            {
              date: '2024-12-31',
              day_name: 'Tuesday',
              events: [
                {
                  id: 'event-9',
                  summary: 'New Year\'s Eve',
                  is_all_day: true,
                },
                {
                  id: 'event-10',
                  summary: 'NYE Party',
                  start: '2024-12-31T21:00:00',
                  is_all_day: false,
                  location: 'Downtown',
                },
              ],
              tasks: [],
            },
          ],
          overdue_tasks: [],
          todoist_connected: false,
          calendar_connected: true,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('.planner-item.all-day');
    await page.waitForTimeout(300);

    await expect(page.locator('.dashboard-day').first()).toHaveScreenshot('all-day-event.png');
  });

  test('action buttons default state', async ({ page }) => {
    await page.goto('/#/planner');
    await page.waitForSelector('#planner-dashboard');
    await page.waitForTimeout(300);

    await expect(page.locator('.dashboard-header')).toHaveScreenshot('buttons-default.png');
  });

  test('refresh button hover', async ({ page }) => {
    await page.goto('/#/planner');
    await page.waitForSelector('.planner-refresh-btn');

    await page.locator('.planner-refresh-btn').hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.dashboard-header')).toHaveScreenshot('refresh-hover.png');
  });

  test('reset button hover', async ({ page }) => {
    await page.goto('/#/planner');
    await page.waitForSelector('.planner-reset-btn');

    await page.locator('.planner-reset-btn').hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.dashboard-header')).toHaveScreenshot('reset-hover.png');
  });
});

test.describe('Visual: Planner Dashboard - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } }); // iPhone SE

  test.beforeEach(async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: true },
    });
  });

  test('mobile dashboard layout', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [
                {
                  id: 'event-1',
                  summary: 'Morning Meeting',
                  start: '2024-12-25T09:00:00',
                  end: '2024-12-25T10:00:00',
                  is_all_day: false,
                  location: 'Conference Room',
                },
              ],
              tasks: [
                {
                  id: 'task-1',
                  content: 'Review code',
                  priority: 3,
                  project_name: 'Development',
                },
              ],
            },
          ],
          overdue_tasks: [
            {
              id: 'overdue-1',
              content: 'Urgent task',
              priority: 4,
              project_name: 'Work',
              due_string: 'Dec 20',
            },
          ],
          todoist_connected: true,
          calendar_connected: true,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('#planner-dashboard');
    await page.waitForTimeout(500);

    await expect(page).toHaveScreenshot('mobile-dashboard.png', { fullPage: true });
  });

  test('mobile action buttons layout', async ({ page }) => {
    await page.goto('/#/planner');
    await page.waitForSelector('.dashboard-actions');
    await page.waitForTimeout(300);

    await expect(page.locator('.dashboard-header')).toHaveScreenshot('mobile-buttons.png');
  });
});

test.describe('Visual: Planner Integration States', () => {
  test('only todoist connected', async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: true, calendar: false },
    });

    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [],
              tasks: [
                {
                  id: 'task-1',
                  content: 'Todoist task',
                  priority: 2,
                  project_name: 'Work',
                },
              ],
            },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: false,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('#planner-dashboard');
    await page.waitForTimeout(300);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('todoist-only.png');
  });

  test('only calendar connected', async ({ page }) => {
    await page.request.post('/test/set-planner-integrations', {
      data: { todoist: false, calendar: true },
    });

    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [
                {
                  id: 'event-1',
                  summary: 'Calendar event',
                  start: '2024-12-25T10:00:00',
                  is_all_day: false,
                },
              ],
              tasks: [],
            },
          ],
          overdue_tasks: [],
          todoist_connected: false,
          calendar_connected: true,
          server_time: '2024-12-25T10:00:00',
        },
      },
    });

    await page.goto('/#/planner');
    await page.waitForSelector('#planner-dashboard');
    await page.waitForTimeout(300);

    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('calendar-only.png');
  });
});
