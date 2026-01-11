import { escapeHtml, getElementById } from '../utils/dom';
import { COPY_ICON, CHECK_ICON, REFRESH_ICON, CLEAR_ICON, CALENDAR_ICON, MAP_PIN_ICON, SUN_ICON, SUNRISE_ICON, SPARKLES_ICON, CHECKLIST_ICON } from '../utils/icons';
import { createLogger } from '../utils/logger';
import type { PlannerDashboard, PlannerDay, PlannerEvent, PlannerTask } from '../types/api';

const log = createLogger('planner-dashboard');

/**
 * Create a dashboard element that can be inserted into the messages container.
 * This renders the dashboard as a special "message-like" element that scrolls with messages.
 */
export function createDashboardElement(
  dashboard: PlannerDashboard,
  onRefresh: () => void,
  onReset: () => void
): HTMLElement {
  log.debug('Creating dashboard element', {
    days: dashboard.days.length,
    overdueTasks: dashboard.overdue_tasks.length,
  });

  const element = document.createElement('div');
  element.className = 'planner-dashboard-message';
  element.id = 'planner-dashboard';

  // Build dashboard content HTML
  let contentHtml = '';

  // Errors if any
  if (dashboard.todoist_error || dashboard.calendar_error) {
    contentHtml += renderErrors(dashboard);
  }

  // Overdue tasks section (if any)
  if (dashboard.overdue_tasks.length > 0) {
    contentHtml += renderOverdueSection(dashboard.overdue_tasks);
  }

  // Today and Tomorrow - always expanded
  if (dashboard.days.length >= 2) {
    contentHtml += renderDaySection(dashboard.days[0]); // Today
    contentHtml += renderDaySection(dashboard.days[1]); // Tomorrow
  }

  // Rest of the week - collapsible
  if (dashboard.days.length > 2) {
    const weekDays = dashboard.days.slice(2);
    const weekItemCount = weekDays.reduce(
      (count, day) => count + day.events.length + day.tasks.length,
      0
    );
    contentHtml += renderWeekSection(weekDays, weekItemCount);
  }

  // Empty state if no data
  if (
    dashboard.days.every((day) => day.events.length === 0 && day.tasks.length === 0) &&
    dashboard.overdue_tasks.length === 0
  ) {
    contentHtml += `
      <div class="dashboard-empty">
        <div class="dashboard-empty-icon">${CHECK_ICON}</div>
        <p>No events or tasks scheduled</p>
        <p>Your calendar and task list are clear!</p>
      </div>
    `;
  }

  element.innerHTML = `
    <div class="dashboard-header">
      <span class="dashboard-title">Your Schedule</span>
      <div class="dashboard-actions">
        <button class="planner-refresh-btn" title="Fetch latest data from Todoist and Google Calendar">
          ${REFRESH_ICON}
          <span>Refresh</span>
        </button>
        <button class="planner-reset-btn" title="Clear all messages and start fresh (triggers new proactive analysis)">
          ${CLEAR_ICON}
          <span>Reset</span>
        </button>
      </div>
    </div>
    <div class="dashboard-content">
      ${contentHtml}
    </div>
  `;

  // Set up refresh button handler
  const refreshBtn = element.querySelector('.planner-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', (e) => {
      e.preventDefault();
      onRefresh();
    });
  }

  // Set up reset button handler
  const resetBtn = element.querySelector('.planner-reset-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      onReset();
    });
  }

  // Set up click-to-copy handlers
  setupCopyHandlers(element);

  log.debug('Dashboard element created');
  return element;
}

/**
 * Render the planner dashboard directly into the #planner-dashboard container.
 * This is a legacy function - prefer createDashboardElement for new code.
 */
export function renderPlannerDashboard(dashboard: PlannerDashboard): void {
  log.debug('Rendering planner dashboard (legacy)', {
    days: dashboard.days.length,
    overdueTasks: dashboard.overdue_tasks.length,
  });

  const container = getElementById<HTMLDivElement>('planner-dashboard');
  if (!container) {
    log.error('Dashboard container not found');
    return;
  }

  // Build HTML (same as createDashboardElement but without wrapper)
  let html = '';

  // Errors if any
  if (dashboard.todoist_error || dashboard.calendar_error) {
    html += renderErrors(dashboard);
  }

  // Overdue tasks section (if any)
  if (dashboard.overdue_tasks.length > 0) {
    html += renderOverdueSection(dashboard.overdue_tasks);
  }

  // Today and Tomorrow - always expanded
  if (dashboard.days.length >= 2) {
    html += renderDaySection(dashboard.days[0]); // Today
    html += renderDaySection(dashboard.days[1]); // Tomorrow
  }

  // Rest of the week - collapsible
  if (dashboard.days.length > 2) {
    const weekDays = dashboard.days.slice(2);
    const weekItemCount = weekDays.reduce(
      (count, day) => count + day.events.length + day.tasks.length,
      0
    );
    html += renderWeekSection(weekDays, weekItemCount);
  }

  // Empty state if no data
  if (
    dashboard.days.every((day) => day.events.length === 0 && day.tasks.length === 0) &&
    dashboard.overdue_tasks.length === 0
  ) {
    html += `
      <div class="dashboard-empty">
        <div class="dashboard-empty-icon">${CHECK_ICON}</div>
        <p>No events or tasks scheduled</p>
        <p>Your calendar and task list are clear!</p>
      </div>
    `;
  }

  container.innerHTML = html;

  // Set up click-to-copy handlers
  setupCopyHandlers(container);

  log.debug('Dashboard rendered');
}

/**
 * Render error messages for failed integrations.
 */
function renderErrors(dashboard: PlannerDashboard): string {
  let html = '';

  if (dashboard.todoist_error) {
    html += `
      <div class="dashboard-error">
        <strong>Todoist:</strong> ${escapeHtml(dashboard.todoist_error)}
      </div>
    `;
  }

  if (dashboard.calendar_error) {
    html += `
      <div class="dashboard-error">
        <strong>Calendar:</strong> ${escapeHtml(dashboard.calendar_error)}
      </div>
    `;
  }

  return html;
}

/**
 * Render overdue tasks section.
 */
function renderOverdueSection(tasks: PlannerTask[]): string {
  const taskItems = tasks.map((task) => renderTaskItem(task)).join('');

  return `
    <div class="dashboard-section overdue">
      <h3>Overdue (${tasks.length})</h3>
      <div class="dashboard-tasks">
        ${taskItems}
      </div>
    </div>
  `;
}

/**
 * Render a day section (Today, Tomorrow, or a weekday).
 */
function renderDaySection(day: PlannerDay): string {
  const hasContent = day.events.length > 0 || day.tasks.length > 0;
  const dayLabel = formatDayLabel(day.day_name, day.date);

  if (!hasContent) {
    return `
      <div class="dashboard-day">
        <div class="dashboard-day-header">
          ${dayLabel}
          <span class="dashboard-day-date">${formatDate(day.date)}</span>
        </div>
        <div class="dashboard-day-empty">
          <p>No events or tasks</p>
        </div>
      </div>
    `;
  }

  let content = '';

  // Events
  if (day.events.length > 0) {
    content += `
      <div class="dashboard-events">
        <div class="dashboard-events-header">
          <span class="dashboard-section-icon">${SPARKLES_ICON}</span>
          Events
        </div>
        ${day.events.map((event) => renderEventItem(event)).join('')}
      </div>
    `;
  }

  // Tasks
  if (day.tasks.length > 0) {
    content += `
      <div class="dashboard-tasks">
        <div class="dashboard-tasks-header">
          <span class="dashboard-section-icon">${CHECKLIST_ICON}</span>
          Tasks
        </div>
        ${day.tasks.map((task) => renderTaskItem(task)).join('')}
      </div>
    `;
  }

  return `
    <div class="dashboard-day">
      <div class="dashboard-day-header">
        ${dayLabel}
        <span class="dashboard-day-date">${formatDate(day.date)}</span>
      </div>
      ${content}
    </div>
  `;
}

/**
 * Render the collapsible "This Week" section.
 */
function renderWeekSection(days: PlannerDay[], itemCount: number): string {
  const daysHtml = days.map((day) => renderDaySection(day)).join('');

  return `
    <div class="dashboard-section">
      <details>
        <summary>This Week (${itemCount} items)</summary>
        <div>
          ${daysHtml}
        </div>
      </details>
    </div>
  `;
}

/**
 * Render a single event item.
 */
function renderEventItem(event: PlannerEvent): string {
  const time = event.is_all_day
    ? 'All day'
    : formatEventTime(event.start, event.end);

  const locationHtml = event.location
    ? `<a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}" target="_blank" rel="noopener noreferrer" class="planner-item-location"><span class="location-icon">${MAP_PIN_ICON}</span>${escapeHtml(event.location)}</a>`
    : '';

  // Build copy text
  const copyText = buildEventCopyText(event);

  return `
    <div class="planner-item planner-item-event ${event.is_all_day ? 'all-day' : ''}" data-copy-text="${escapeHtml(copyText)}">
      <div class="planner-item-time">
        <span>${time}</span>
        <button class="planner-item-copy" title="Copy to clipboard">
          ${COPY_ICON}
        </button>
      </div>
      <div class="planner-item-text">
        <span>${escapeHtml(event.summary)}</span>
        ${locationHtml}
      </div>
    </div>
  `;
}

function renderTaskItem(task: PlannerTask): string {
  const projectHtml = task.project_name
    ? ` <span class="planner-item-project">${escapeHtml(task.project_name)}</span>`
    : '';

  // Build copy text
  const copyText = buildTaskCopyText(task);

  return `
    <div class="planner-item planner-item-task" data-priority="${task.priority}" data-copy-text="${escapeHtml(copyText)}">
      <div class="planner-item-content">
        <div class="planner-item-text">${escapeHtml(task.content)}${projectHtml}</div>
        <button class="planner-item-copy" title="Copy to clipboard">
          ${COPY_ICON}
        </button>
      </div>
    </div>
  `;
}

/**
 * Format a date for display (e.g., "Jan 15").
 */
function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * Get icon for day based on day name.
 */
function getDayIcon(dayName: string): string {
  if (dayName === 'Today') return SUN_ICON;
  if (dayName === 'Tomorrow') return SUNRISE_ICON;
  return CALENDAR_ICON;
}

/**
 * Format day label with day of week for Today/Tomorrow.
 * Examples: "Today (Monday)", "Tomorrow (Tuesday)", "Wednesday"
 */
function formatDayLabel(dayName: string, dateStr: string): string {
  const date = new Date(dateStr);
  const dayOfWeek = date.toLocaleDateString(undefined, { weekday: 'long' });

  const icon = getDayIcon(dayName);
  const iconHtml = `<span class="dashboard-day-icon">${icon}</span>`;

  if (dayName === 'Today' || dayName === 'Tomorrow') {
    return `${iconHtml}${escapeHtml(`${dayName} (${dayOfWeek})`)}`;
  }

  return `${iconHtml}${escapeHtml(dayName)}`;
}

/**
 * Format event time range.
 */
function formatEventTime(start?: string | null, end?: string | null): string {
  if (!start) return '';

  const startDate = new Date(start);
  const startTime = startDate.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  });

  if (!end) return startTime;

  const endDate = new Date(end);
  const endTime = endDate.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  });

  return `${startTime}-${endTime}`;
}

/**
 * Build copy text for an event.
 */
function buildEventCopyText(event: PlannerEvent): string {
  let text = event.summary;

  if (event.is_all_day) {
    text += ' (All day)';
  } else if (event.start) {
    const time = formatEventTime(event.start, event.end);
    text += ` at ${time}`;
  }

  if (event.location) {
    text += ` - ${event.location}`;
  }

  return text;
}

/**
 * Build copy text for a task.
 */
function buildTaskCopyText(task: PlannerTask): string {
  let text = task.content;

  if (task.project_name) {
    text += ` (${task.project_name})`;
  }

  if (task.due_string) {
    text += ` - Due: ${task.due_string}`;
  }

  return text;
}

/**
 * Set up click-to-copy handlers for all planner items.
 */
function setupCopyHandlers(container: HTMLElement): void {
  container.addEventListener('click', async (e) => {
    const target = e.target as HTMLElement;
    const copyBtn = target.closest('.planner-item-copy');

    if (!copyBtn) return;

    const plannerItem = copyBtn.closest('.planner-item');
    if (!plannerItem) return;

    const copyText = plannerItem.getAttribute('data-copy-text');
    if (!copyText) return;

    try {
      await navigator.clipboard.writeText(copyText);

      // Show success feedback
      copyBtn.innerHTML = CHECK_ICON;
      copyBtn.classList.add('copied');

      setTimeout(() => {
        copyBtn.innerHTML = COPY_ICON;
        copyBtn.classList.remove('copied');
      }, 2000);

      log.debug('Copied to clipboard', { text: copyText });
    } catch (err) {
      log.error('Failed to copy to clipboard', { error: err });
    }
  });
}

/**
 * Show loading state in the dashboard.
 */
export function showDashboardLoading(): void {
  const container = getElementById<HTMLDivElement>('planner-dashboard');
  if (!container) return;

  container.innerHTML = `
    <div class="dashboard-loading">
      <div class="loading-spinner"></div>
      <p>Loading your schedule...</p>
    </div>
  `;
}

/**
 * Show error state in the dashboard.
 */
export function showDashboardError(message: string): void {
  const container = getElementById<HTMLDivElement>('planner-dashboard');
  if (!container) return;

  container.innerHTML = `
    <div class="dashboard-error">
      <strong>Error:</strong> ${escapeHtml(message)}
    </div>
  `;
}

/**
 * Create a loading element for the dashboard.
 */
export function createDashboardLoadingElement(): HTMLElement {
  const element = document.createElement('div');
  element.className = 'planner-dashboard-message loading';
  element.id = 'planner-dashboard';
  element.innerHTML = `
    <div class="dashboard-loading">
      <div class="dashboard-loading-icon">${CALENDAR_ICON}</div>
      <div class="dashboard-loading-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <p class="dashboard-loading-text">Loading your schedule...</p>
    </div>
  `;
  return element;
}
