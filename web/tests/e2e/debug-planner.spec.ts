/**
 * Debug test to capture console errors for planner dashboard
 */
import { test } from '../global-setup';

test('capture planner console errors', async ({ page }) => {
  // Capture console messages
  const consoleMessages: string[] = [];
  page.on('console', msg => {
    consoleMessages.push(`[${msg.type()}] ${msg.text()}`);
  });

  // Capture page errors
  const pageErrors: string[] = [];
  page.on('pageerror', error => {
    pageErrors.push(`PAGE ERROR: ${error.message}\n${error.stack}`);
  });

  await page.request.post('/test/set-planner-integrations', {
    data: { todoist: true, calendar: true },
  });

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
  await page.waitForTimeout(5000);

  console.log('\n=== CONSOLE MESSAGES ===');
  consoleMessages.forEach(msg => console.log(msg));

  console.log('\n=== PAGE ERRORS ===');
  pageErrors.forEach(err => console.log(err));

  console.log('\n=== DASHBOARD EXISTS ===');
  const dashboard = await page.locator('#planner-dashboard').count();
  console.log('Dashboard elements found:', dashboard);

  console.log('\n=== MESSAGES CONTAINER ===');
  const messagesContent = await page.locator('#messages').innerHTML();
  console.log(messagesContent);

  console.log('\n=== ERROR ELEMENT ===');
  const errorCount = await page.locator('.dashboard-error').count();
  console.log('Error elements found:', errorCount);
  if (errorCount > 0) {
    const errorText = await page.locator('.dashboard-error').textContent();
    console.log('Error text:', errorText);
  }
});
