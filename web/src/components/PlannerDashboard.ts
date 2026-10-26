import { createElement } from '../utils/dom';
import { COPY_ICON, CHECK_ICON, REFRESH_ICON, CLEAR_ICON, CALENDAR_ICON, MAP_PIN_ICON, HEART_ICON, MOON_ICON, BATTERY_ICON, STRESS_ICON, READINESS_ICON, STEPS_ICON, createIconButton, createIconElement, getWeatherIcon, iconNodes, setIcon, type IconHtml } from '../utils/icons';
import { createLogger } from '../utils/logger';
import { createEmptyState } from './EmptyState';
import type { PlannerDashboard, PlannerDay, PlannerEvent, PlannerTask, PlannerHealthSummary } from '../types/api';

const log = createLogger('planner-dashboard');
const el = createElement;

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

  const labeledButton = (className: string, title: string, icon: IconHtml, label: string): HTMLButtonElement =>
    el('button', { class: className, title }, [iconNodes(icon), el('span', {}, [label])]);
  element.append(
    el('div', { class: 'dashboard-header' }, [
      el('div', { class: 'dashboard-title' }, [
        el('span', { class: 'dashboard-title-text' }, ['Your Schedule']),
        el('span', { class: 'dashboard-date' }, [todayLine]),
      ]),
      el('div', { class: 'dashboard-actions' }, [
        labeledButton('planner-refresh-btn', 'Fetch latest data from Todoist and Google Calendar', REFRESH_ICON, 'Refresh'),
        labeledButton(
          'planner-reset-btn',
          'Clear all messages and start fresh (triggers new proactive analysis)',
          CLEAR_ICON,
          'Reset'
        ),
      ]),
    ]),
    el('div', { class: 'dashboard-content' }, buildDashboardContent(dashboard))
  );

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

type Child = Node | string | null | false | undefined;

/**
 * Build the inner content (health strip, errors, overdue, days, week).
 */
function buildDashboardContent(dashboard: PlannerDashboard): Child[] {
  const content: Child[] = [];

  // Health summary strip (if Garmin connected)
  if (dashboard.health_summary && dashboard.garmin_connected) {
    content.push(healthSummary(dashboard.health_summary));
  }

  // Errors if any
  if (dashboard.todoist_error || dashboard.calendar_error || dashboard.garmin_error || dashboard.weather_error) {
    content.push(...errorLines(dashboard));
  }

  // Nothing at all scheduled (and every source answered): the empty state
  // alone says so - per-day "Nothing scheduled" lines above it repeated it.
  // Never "all clear" when a task or calendar source failed: its items are
  // unknown, not absent.
  const allClear =
    !dashboard.todoist_error &&
    !dashboard.calendar_error &&
    dashboard.days.every((day) => day.events.length === 0 && day.tasks.length === 0) &&
    dashboard.overdue_tasks.length === 0;
  if (allClear) {
    content.push(
      createEmptyState({
        icon: CHECK_ICON,
        title: 'No events or tasks scheduled',
        hint: 'Your calendar and task list are clear!',
        variant: 'success',
        className: 'dashboard-empty',
      })
    );
    return content;
  }

  // Overdue tasks section (if any)
  if (dashboard.overdue_tasks.length > 0) {
    content.push(overdueSection(dashboard.overdue_tasks));
  }

  // Today and Tomorrow - always expanded
  const [today, tomorrow] = dashboard.days;
  if (today) {
    const serverNow = new Date(dashboard.server_time);
    content.push(daySection(today, true, serverNow)); // Today

    if (tomorrow) {
      content.push(daySection(tomorrow)); // Tomorrow
    }
  }

  // Rest of the week - collapsible
  if (dashboard.days.length > 2) {
    const weekDays = dashboard.days.slice(2);
    const weekItemCount = weekDays.reduce(
      (count, day) => count + day.events.length + day.tasks.length,
      0
    );
    content.push(weekSection(weekDays, weekItemCount));
  }

  return content;
}

/**
 * Error messages for failed integrations.
 */
function errorLines(dashboard: PlannerDashboard): HTMLElement[] {
  const errors: Array<[string, string | null | undefined]> = [
    ['Todoist', dashboard.todoist_error],
    ['Calendar', dashboard.calendar_error],
    ['Garmin', dashboard.garmin_error],
    ['Weather', dashboard.weather_error],
  ];

  return errors
    .filter(([, message]) => message)
    .map(([source, message]) =>
      el('div', { class: 'dashboard-error' }, [el('strong', {}, [`${source}:`]), ` ${message ?? ''}`])
    );
}

/**
 * The overdue tasks section.
 */
function overdueSection(tasks: PlannerTask[]): HTMLElement {
  return el('div', { class: 'dashboard-section overdue' }, [
    el('h3', {}, [`Overdue (${tasks.length})`]),
    el('div', { class: 'dashboard-tasks' }, tasks.map(taskItem)),
  ]);
}

/**
 * A day's events in order; today's get past events dimmed and the time
 * indicator between past and future timed events (all-day events skipped).
 */
function dayEvents(events: PlannerDay['events'], isToday: boolean, now: Date): HTMLElement[] {
  const items: HTMLElement[] = [];
  let timeIndicatorInserted = false;
  for (const event of events) {
    const isPast = isToday && isEventPast(event, now);

    // Insert time indicator between past and future timed events (skip all-day)
    if (isToday && !timeIndicatorInserted && !event.is_all_day && !isPast) {
      items.push(timeIndicator(now));
      timeIndicatorInserted = true;
    }

    items.push(eventItem(event, isPast));
  }

  // If all timed events are past, insert time indicator after the last one
  const hasTimedEvents = events.some((e) => !e.is_all_day);
  if (isToday && !timeIndicatorInserted && hasTimedEvents) {
    items.push(timeIndicator(now));
  }
  return items;
}

/**
 * A day section (Today, Tomorrow, or a weekday).
 * @param isToday - If true, adds time indicator and dims past events
 */
function daySection(day: PlannerDay, isToday = false, now = new Date()): HTMLElement {
  const hasContent = day.events.length > 0 || day.tasks.length > 0;
  const header = dayHeader(day);

  if (!hasContent) {
    return el('section', { class: 'dashboard-day' }, [
      header,
      el('div', { class: 'dashboard-day-empty' }, [el('p', {}, ['Nothing scheduled'])]),
    ]);
  }

  const content: Child[] = [];

  // Events
  if (day.events.length > 0) {
    content.push(
      el('div', { class: 'dashboard-events' }, [
        el('div', { class: 'dashboard-events-header' }, ['Events']),
        ...dayEvents(day.events, isToday, now),
      ])
    );
  } else if (isToday) {
    // No events but still today - show time indicator before tasks
    content.push(timeIndicator(now));
  }

  // Tasks
  if (day.tasks.length > 0) {
    content.push(
      el('div', { class: 'dashboard-tasks' }, [
        el('div', { class: 'dashboard-tasks-header' }, ['Tasks']),
        ...day.tasks.map(taskItem),
      ])
    );
  }

  return el('section', { class: 'dashboard-day' }, [header, ...content]);
}

/**
 * A day heading: display-face day name, muted date, weather at right.
 */
function dayHeader(day: PlannerDay): HTMLElement {
  const date = new Date(day.date);
  const weekday = date.toLocaleDateString(undefined, { weekday: 'long' });
  const isNamedDay = day.day_name === 'Today' || day.day_name === 'Tomorrow';
  const meta = isNamedDay ? `${weekday} · ${formatDate(day.date)}` : formatDate(day.date);

  return el('header', { class: 'dashboard-day-header' }, [
    el('span', { class: 'dashboard-day-name' }, [day.day_name]),
    el('span', { class: 'dashboard-day-meta' }, [meta]),
    weatherBadge(day),
  ]);
}

/**
 * The collapsible "This Week" section.
 */
function weekSection(days: PlannerDay[], itemCount: number): HTMLElement {
  return el('div', { class: 'dashboard-section week' }, [
    el('details', {}, [
      el('summary', {}, [`This Week (${itemCount} ${itemCount === 1 ? 'item' : 'items'})`]),
      el('div', {}, days.map((day) => daySection(day))),
    ]),
  ]);
}

/** The copy-to-clipboard button at the end of a row. */
function copyButton(): HTMLButtonElement {
  return createIconButton(
    { class: 'planner-item-copy', title: 'Copy to clipboard', 'aria-label': 'Copy to clipboard' },
    COPY_ICON
  );
}

/**
 * A single event item as a timeline row: fixed time column,
 * title with optional calendar/location chips, copy affordance at the end.
 * @param isPast - If true, dims the event (for today's past events)
 */
function eventItem(event: PlannerEvent, isPast = false): HTMLElement {
  const time = event.is_all_day
    ? 'All day'
    : formatEventTime(event.start, event.end);

  const locationChip =
    !!event.location &&
    el(
      'a',
      {
        class: 'planner-item-location',
        href: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(event.location)}`,
        target: '_blank',
        rel: 'noopener noreferrer',
      },
      [createIconElement('location-icon', MAP_PIN_ICON), event.location]
    );

  // Show calendar name for non-primary calendars
  const isPrimaryCalendar = !event.calendar_id || event.calendar_id === 'primary';
  const calendarChip =
    !isPrimaryCalendar && !!event.calendar_summary && el('span', { class: 'planner-item-calendar' }, [event.calendar_summary]);

  return el(
    'div',
    {
      class: `planner-item planner-item-event ${event.is_all_day ? 'all-day' : ''}`,
      ...(isPast ? { 'data-past': 'true' } : {}),
      'data-copy-text': buildEventCopyText(event),
    },
    [
      el('span', { class: 'planner-item-time' }, [time]),
      el('div', { class: 'planner-item-body' }, [
        el('span', { class: 'planner-item-title' }, [event.summary]),
        calendarChip,
        locationChip,
      ]),
      copyButton(),
    ]
  );
}

/**
 * A single task as a compact checkbox-ring row; the ring color
 * carries the Todoist priority.
 */
function taskItem(task: PlannerTask): HTMLElement {
  return el(
    'div',
    { class: 'planner-item planner-item-task', 'data-priority': String(task.priority), 'data-copy-text': buildTaskCopyText(task) },
    [
      el('span', { class: 'planner-task-ring', 'aria-hidden': 'true' }),
      el('div', { class: 'planner-item-body' }, [
        el('span', { class: 'planner-item-title' }, [task.content]),
        !!task.project_name && el('span', { class: 'planner-item-project' }, [task.project_name]),
      ]),
      copyButton(),
    ]
  );
}

/**
 * The health summary strip (null with no metrics).
 */
function healthSummary(health: PlannerHealthSummary): HTMLElement | null {
  const metrics: HTMLElement[] = [];

  if (health.training_readiness?.score != null) {
    const level = health.training_readiness.level || '';
    metrics.push(healthMetric(READINESS_ICON, String(Math.round(health.training_readiness.score)), `Readiness${level ? ` (${level})` : ''}`));
  }

  if (health.sleep?.duration_hours != null) {
    const quality = health.sleep.quality || '';
    metrics.push(healthMetric(MOON_ICON, `${health.sleep.duration_hours}h`, `Sleep${quality ? ` (${quality})` : ''}`));
  }

  if (health.resting_hr != null) {
    metrics.push(healthMetric(HEART_ICON, String(health.resting_hr), 'Resting HR'));
  }

  if (health.body_battery != null) {
    metrics.push(healthMetric(BATTERY_ICON, String(health.body_battery), 'Body Battery'));
  }

  if (health.stress_avg != null) {
    metrics.push(healthMetric(STRESS_ICON, String(Math.round(health.stress_avg)), 'Stress'));
  }

  if (health.steps_today != null) {
    metrics.push(healthMetric(STEPS_ICON, health.steps_today.toLocaleString(), 'Steps'));
  }

  if (metrics.length === 0) return null;

  return el('div', { class: 'health-summary-strip' }, metrics);
}

function healthMetric(icon: IconHtml, value: string, label: string): HTMLElement {
  return el('div', { class: 'health-metric' }, [
    createIconElement('health-metric-icon', icon),
    el('span', { class: 'health-metric-value' }, [value]),
    el('span', { class: 'health-metric-label' }, [label]),
  ]);
}

/**
 * The weather badge of a day header (null without a forecast).
 */
function weatherBadge(day: PlannerDay): HTMLElement | null {
  if (!day.weather) return null;
  const w = day.weather;
  if (w.temperature_high == null && w.temperature_low == null) return null;

  const tempLow = w.temperature_low != null ? `${Math.round(w.temperature_low)}°` : '';
  const tempHigh = w.temperature_high != null ? `${Math.round(w.temperature_high)}°` : '';
  const tempRange = tempLow && tempHigh ? `${tempLow}/${tempHigh}` : tempLow || tempHigh;
  const precip = w.precipitation > 0 ? ` ${w.precipitation.toFixed(1)}mm` : '';

  return el('span', { class: 'weather-badge' }, [
    createIconElement('weather-badge-icon', getWeatherIcon(w.symbol_code)),
    el('span', { class: 'weather-badge-temp' }, [tempRange]),
    !!precip && el('span', { class: 'weather-badge-precip' }, [precip]),
  ]);
}

/**
 * The time indicator ("Now" line) for today's section.
 */
function timeIndicator(now: Date): HTMLElement {
  const timeStr = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  return el('div', { class: 'time-indicator' }, [
    el('span', { class: 'time-indicator-label' }, [`Now · ${timeStr}`]),
    el('div', { class: 'time-indicator-line' }),
  ]);
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
  const copyItem = async (e: MouseEvent): Promise<void> => {
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
      setIcon(copyBtn, CHECK_ICON);
      copyBtn.classList.add('copied');

      setTimeout(() => {
        setIcon(copyBtn, COPY_ICON);
        copyBtn.classList.remove('copied');
      }, 2000);

      log.debug('Copied to clipboard', { length: copyText.length });
    } catch (err) {
      log.error('Failed to copy to clipboard', { error: err });
    }
  };
  container.addEventListener('click', (e) => {
    void copyItem(e);
  });
}

/**
 * Create a loading element for the dashboard.
 */
export function createDashboardLoadingElement(): HTMLElement {
  const element = document.createElement('div');
  element.className = 'planner-dashboard-message loading';
  element.id = 'planner-dashboard';
  element.appendChild(
    createElement('div', { class: 'dashboard-loading' }, [
      createIconElement('dashboard-loading-icon', CALENDAR_ICON, 'div'),
      createElement('div', { class: 'dashboard-loading-dots' }, [
        createElement('span'),
        createElement('span'),
        createElement('span'),
      ]),
      createElement('p', { class: 'dashboard-loading-text' }, ['Loading your schedule...']),
    ])
  );
  return element;
}
