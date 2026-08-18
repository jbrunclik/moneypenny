import { escapeHtml } from '../utils/dom';
import { COPY_ICON, CHECK_ICON, REFRESH_ICON, CLEAR_ICON, CALENDAR_ICON, MAP_PIN_ICON, HEART_ICON, MOON_ICON, BATTERY_ICON, STRESS_ICON, READINESS_ICON, STEPS_ICON, getWeatherIcon } from '../utils/icons';
import { createLogger } from '../utils/logger';
import type { PlannerDashboard, PlannerDay, PlannerEvent, PlannerTask, PlannerHealthSummary } from '../types/api';

const log = createLogger('planner-dashboard');

/**
 * Create a dashboard element that can be inserted into the messages container.
 * Renders a text-forward agenda: day sections with display-face headings,
 * a fixed time column for events, and compact checkbox-ring task rows.
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

  const serverNow = new Date(dashboard.server_time);
  const todayLine = serverNow.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

  element.innerHTML = `
    <div class="dashboard-header">
      <div class="dashboard-title">
        <span class="dashboard-title-text">Your Schedule</span>
        <span class="dashboard-date">${escapeHtml(todayLine)}</span>
      </div>
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
      ${buildDashboardContent(dashboard)}
    </div>
  `;

  const refreshBtn = element.querySelector('.planner-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', (e) => {
      e.preventDefault();
      onRefresh();
    });
  }

  const resetBtn = element.querySelector('.planner-reset-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      onReset();
    });
  }

  setupCopyHandlers(element);

  log.debug('Dashboard element created');
  return element;
}

/**
 * Build the inner content HTML (health strip, errors, overdue, days, week).
 */
function buildDashboardContent(dashboard: PlannerDashboard): string {
  let html = '';

  // Health summary strip (if Garmin connected)
  if (dashboard.health_summary && dashboard.garmin_connected) {
    html += renderHealthSummary(dashboard.health_summary);
  }

  // Errors if any
  if (dashboard.todoist_error || dashboard.calendar_error || dashboard.garmin_error || dashboard.weather_error) {
    html += renderErrors(dashboard);
  }

  // Overdue tasks section (if any)
  if (dashboard.overdue_tasks.length > 0) {
    html += renderOverdueSection(dashboard.overdue_tasks);
  }

  // Today and Tomorrow - always expanded
  if (dashboard.days.length >= 1) {
    const serverNow = new Date(dashboard.server_time);
    html += renderDaySection(dashboard.days[0], true, serverNow); // Today

    if (dashboard.days.length >= 2) {
      html += renderDaySection(dashboard.days[1]); // Tomorrow
    }
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

  return html;
}

/**
 * Render error messages for failed integrations.
 */
function renderErrors(dashboard: PlannerDashboard): string {
  const errors: Array<[string, string | null | undefined]> = [
    ['Todoist', dashboard.todoist_error],
    ['Calendar', dashboard.calendar_error],
    ['Garmin', dashboard.garmin_error],
    ['Weather', dashboard.weather_error],
  ];

  return errors
    .filter(([, message]) => message)
    .map(
      ([source, message]) => `
        <div class="dashboard-error">
          <strong>${source}:</strong> ${escapeHtml(message as string)}
        </div>
      `
    )
    .join('');
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
 * @param isToday - If true, adds time indicator and dims past events
 */
function renderDaySection(day: PlannerDay, isToday = false, now = new Date()): string {
  const hasContent = day.events.length > 0 || day.tasks.length > 0;
  const header = renderDayHeader(day);

  if (!hasContent) {
    return `
      <section class="dashboard-day">
        ${header}
        <div class="dashboard-day-empty">
          <p>Nothing scheduled</p>
        </div>
      </section>
    `;
  }

  let content = '';
  let timeIndicatorInserted = false;

  // Events
  if (day.events.length > 0) {
    let eventsHtml = '';
    for (const event of day.events) {
      const isPast = isToday && isEventPast(event, now);

      // Insert time indicator between past and future timed events (skip all-day)
      if (isToday && !timeIndicatorInserted && !event.is_all_day && !isPast) {
        eventsHtml += renderTimeIndicator(now);
        timeIndicatorInserted = true;
      }

      eventsHtml += renderEventItem(event, isPast);
    }

    // If all timed events are past, insert time indicator after the last one
    const hasTimedEvents = day.events.some((e) => !e.is_all_day);
    if (isToday && !timeIndicatorInserted && hasTimedEvents) {
      eventsHtml += renderTimeIndicator(now);
    }

    content += `
      <div class="dashboard-events">
        <div class="dashboard-events-header">Events</div>
        ${eventsHtml}
      </div>
    `;
  } else if (isToday) {
    // No events but still today - show time indicator before tasks
    content += renderTimeIndicator(now);
  }

  // Tasks
  if (day.tasks.length > 0) {
    content += `
      <div class="dashboard-tasks">
        <div class="dashboard-tasks-header">Tasks</div>
        ${day.tasks.map((task) => renderTaskItem(task)).join('')}
      </div>
    `;
  }

  return `
    <section class="dashboard-day">
      ${header}
      ${content}
    </section>
  `;
}

/**
 * Render a day heading: display-face day name, muted date, weather at right.
 */
function renderDayHeader(day: PlannerDay): string {
  const date = new Date(day.date);
  const weekday = date.toLocaleDateString(undefined, { weekday: 'long' });
  const isNamedDay = day.day_name === 'Today' || day.day_name === 'Tomorrow';
  const meta = isNamedDay ? `${weekday} · ${formatDate(day.date)}` : formatDate(day.date);
  const weatherBadge = renderWeatherBadge(day);

  return `
    <header class="dashboard-day-header">
      <span class="dashboard-day-name">${escapeHtml(day.day_name)}</span>
      <span class="dashboard-day-meta">${escapeHtml(meta)}</span>
      ${weatherBadge}
    </header>
  `;
}

/**
 * Render the collapsible "This Week" section.
 */
function renderWeekSection(days: PlannerDay[], itemCount: number): string {
  const daysHtml = days.map((day) => renderDaySection(day)).join('');

  return `
    <div class="dashboard-section week">
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
 * Render a single event item as a timeline row: fixed time column,
 * title with optional calendar/location chips, copy affordance at the end.
 * @param isPast - If true, dims the event (for today's past events)
 */
function renderEventItem(event: PlannerEvent, isPast = false): string {
  const time = event.is_all_day
    ? 'All day'
    : formatEventTime(event.start, event.end);

  const locationChip = event.location
    ? `<a class="planner-item-location" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}" target="_blank" rel="noopener noreferrer"><span class="location-icon">${MAP_PIN_ICON}</span>${escapeHtml(event.location)}</a>`
    : '';

  // Show calendar name for non-primary calendars
  const isPrimaryCalendar = !event.calendar_id || event.calendar_id === 'primary';
  const calendarChip = !isPrimaryCalendar && event.calendar_summary
    ? `<span class="planner-item-calendar">${escapeHtml(event.calendar_summary)}</span>`
    : '';

  const copyText = buildEventCopyText(event);
  const pastAttr = isPast ? ' data-past="true"' : '';

  return `
    <div class="planner-item planner-item-event ${event.is_all_day ? 'all-day' : ''}"${pastAttr} data-copy-text="${escapeHtml(copyText)}">
      <span class="planner-item-time">${time}</span>
      <div class="planner-item-body">
        <span class="planner-item-title">${escapeHtml(event.summary)}</span>${calendarChip}${locationChip}
      </div>
      <button class="planner-item-copy" title="Copy to clipboard" aria-label="Copy to clipboard">
        ${COPY_ICON}
      </button>
    </div>
  `;
}

/**
 * Render a single task as a compact checkbox-ring row; the ring color
 * carries the Todoist priority.
 */
function renderTaskItem(task: PlannerTask): string {
  const projectChip = task.project_name
    ? `<span class="planner-item-project">${escapeHtml(task.project_name)}</span>`
    : '';

  const copyText = buildTaskCopyText(task);

  return `
    <div class="planner-item planner-item-task" data-priority="${task.priority}" data-copy-text="${escapeHtml(copyText)}">
      <span class="planner-task-ring" aria-hidden="true"></span>
      <div class="planner-item-body">
        <span class="planner-item-title">${escapeHtml(task.content)}</span>${projectChip}
      </div>
      <button class="planner-item-copy" title="Copy to clipboard" aria-label="Copy to clipboard">
        ${COPY_ICON}
      </button>
    </div>
  `;
}

/**
 * Render health summary strip.
 */
function renderHealthSummary(health: PlannerHealthSummary): string {
  const metrics: string[] = [];

  if (health.training_readiness?.score != null) {
    const level = health.training_readiness.level || '';
    metrics.push(renderHealthMetric(READINESS_ICON, String(Math.round(health.training_readiness.score)), `Readiness${level ? ` (${level})` : ''}`));
  }

  if (health.sleep?.duration_hours != null) {
    const quality = health.sleep.quality || '';
    metrics.push(renderHealthMetric(MOON_ICON, `${health.sleep.duration_hours}h`, `Sleep${quality ? ` (${quality})` : ''}`));
  }

  if (health.resting_hr != null) {
    metrics.push(renderHealthMetric(HEART_ICON, String(health.resting_hr), 'Resting HR'));
  }

  if (health.body_battery != null) {
    metrics.push(renderHealthMetric(BATTERY_ICON, String(health.body_battery), 'Body Battery'));
  }

  if (health.stress_avg != null) {
    metrics.push(renderHealthMetric(STRESS_ICON, String(Math.round(health.stress_avg)), 'Stress'));
  }

  if (health.steps_today != null) {
    metrics.push(renderHealthMetric(STEPS_ICON, health.steps_today.toLocaleString(), 'Steps'));
  }

  if (metrics.length === 0) return '';

  return `
    <div class="health-summary-strip">
      ${metrics.join('')}
    </div>
  `;
}

function renderHealthMetric(icon: string, value: string, label: string): string {
  return `
    <div class="health-metric">
      <span class="health-metric-icon">${icon}</span>
      <span class="health-metric-value">${escapeHtml(value)}</span>
      <span class="health-metric-label">${escapeHtml(label)}</span>
    </div>
  `;
}

/**
 * Render weather badge for a day header.
 */
function renderWeatherBadge(day: PlannerDay): string {
  if (!day.weather) return '';
  const w = day.weather;
  if (w.temperature_high == null && w.temperature_low == null) return '';

  const icon = getWeatherIcon(w.symbol_code);
  const tempLow = w.temperature_low != null ? `${Math.round(w.temperature_low)}°` : '';
  const tempHigh = w.temperature_high != null ? `${Math.round(w.temperature_high)}°` : '';
  const tempRange = tempLow && tempHigh ? `${tempLow}/${tempHigh}` : tempLow || tempHigh;
  const precip = w.precipitation > 0 ? ` ${w.precipitation.toFixed(1)}mm` : '';

  return `
    <span class="weather-badge">
      <span class="weather-badge-icon">${icon}</span>
      <span class="weather-badge-temp">${tempRange}</span>${precip ? `<span class="weather-badge-precip">${precip}</span>` : ''}
    </span>
  `;
}

/**
 * Render time indicator ("Now" line) for today's section.
 */
function renderTimeIndicator(now: Date): string {
  const timeStr = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `
    <div class="time-indicator">
      <span class="time-indicator-label">Now · ${timeStr}</span>
      <div class="time-indicator-line"></div>
    </div>
  `;
}

/**
 * Check if an event has ended (is in the past).
 */
function isEventPast(event: PlannerEvent, now: Date): boolean {
  if (event.is_all_day) return false; // All-day events don't dim
  const endStr = event.end || event.start;
  if (!endStr) return false;
  const endDate = new Date(endStr);
  return endDate < now;
}

/**
 * Format a date for display (e.g., "Jan 15").
 */
function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
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
    hour12: false,
  });

  if (!end) return startTime;

  const endDate = new Date(end);
  const endTime = endDate.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

  return `${startTime}–${endTime}`;
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
