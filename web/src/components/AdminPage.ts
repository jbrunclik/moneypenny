/**
 * Admin page (S12): a full-screen read-only overview for the accounts in
 * ADMIN_EMAILS - spend, agent health, web-search quotas, response quality and
 * system facts. Names and numbers only; the backend never sends conversation
 * titles or content.
 */
import { admin } from '../api/admin';
import { createDeviceChecksSection } from './AdminDeviceChecks';
import type { AdminOverview } from '../types/api';
import { createElement, createSvgElement } from '../utils/dom';
import { getFocusableElements, trapTabKey } from '../utils/focus-trap';
import { CHEVRON_LEFT_ICON, REFRESH_ICON, createIconButton } from '../utils/icons';
import { createLogger } from '../utils/logger';

const log = createLogger('components/AdminPage');

type Spend = AdminOverview['spend'];

const CHART_WIDTH = 300;
const CHART_HEIGHT = 80;
const CHART_GAP = 2;
const BYTES_PER_MB = 1024 * 1024;
const MS_PER_SECOND = 1000;

let page: HTMLElement | null = null;
let returnFocusTo: HTMLElement | null = null;

export interface AdminPageOptions {
  /** Start the device check runner (core; the page closes first) */
  onRunDeviceChecks?: () => void;
}

const FEATURE_LABELS: Record<string, string> = {
  chat: 'Chat',
  agents: 'Agents',
  planner: 'Planner',
  sports: 'Sports',
  language: 'Language',
  deleted: 'Deleted chats',
};

function seconds(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? '-' : `${(ms / MS_PER_SECOND).toFixed(1)} s`;
}

function megabytes(bytes: number): string {
  return `${Math.round(bytes / BYTES_PER_MB)} MB`;
}

function dateTime(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '-';
}

type Child = Node | string | null | false | undefined;

const el = createElement;

function section(title: string, body: Child[]): HTMLElement {
  return el('section', { class: 'admin-section' }, [el('h2', {}, [title]), ...body]);
}

/** A labelled number: <div class="admin-stat"><span>label</span><strong>value</strong></div> */
function stat(label: string, value: string, extraClass = ''): HTMLElement {
  return el('div', { class: `admin-stat${extraClass}` }, [el('span', {}, [label]), el('strong', {}, [value])]);
}

function table(head: (string | [string, string])[], rows: HTMLElement[]): HTMLElement {
  const th = (h: string | [string, string]): HTMLElement =>
    typeof h === 'string' ? el('th', {}, [h]) : el('th', { title: h[1] }, [h[0]]);
  return el('table', { class: 'admin-table' }, [
    el('thead', {}, [el('tr', {}, head.map(th))]),
    el('tbody', {}, rows),
  ]);
}

function chart(daily: Spend['daily']): SVGSVGElement {
  const max = Math.max(...daily.map((d) => d.amount.usd), 0);
  const barWidth = (CHART_WIDTH - CHART_GAP * (daily.length - 1)) / daily.length;
  const bars = daily.map((day, i) => {
    const height = max > 0 ? Math.round((day.amount.usd / max) * CHART_HEIGHT) : 0;
    const x = (i * (barWidth + CHART_GAP)).toFixed(1);
    const label = `${day.date}: ${day.amount.formatted}`;
    return createSvgElement(
      'rect',
      { x, y: String(CHART_HEIGHT - height), width: barWidth.toFixed(1), height: String(height) },
      [createSvgElement('title', {}, [label])]
    );
  });
  return createSvgElement(
    'svg',
    {
      class: 'admin-chart',
      viewBox: `0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`,
      preserveAspectRatio: 'none',
      role: 'img',
      'aria-label': 'Spend over the last 30 days',
    },
    bars
  );
}

function shares(title: string, list: Spend['by_feature'], labels: Record<string, string>): HTMLElement {
  return el('div', { class: 'admin-shares' }, [
    el('h3', {}, [title]),
    el(
      'ul',
      {},
      list.map((s) => el('li', {}, [el('span', {}, [labels[s.name] ?? s.name]), el('span', {}, [s.amount.formatted])]))
    ),
  ]);
}

function spendSection(spend: Spend): HTMLElement {
  const users = spend.users.map((u) =>
    el('tr', { class: `admin-user-row${u.over_threshold ? ' admin-over-threshold' : ''}` }, [
      el('td', {}, [u.name]),
      el('td', {}, [u.today.formatted]),
      el('td', {}, [u.month.formatted]),
      el('td', {}, [String(u.month_chats)]),
      el('td', {}, [String(u.month_turns)]),
    ])
  );
  return section('Spend', [
    el('div', { class: 'admin-stats' }, [
      stat('Today', spend.today.formatted, ' admin-spend-today'),
      stat('This month', spend.month.formatted),
    ]),
    table(
      ['Person', 'Today', 'This month', ['Chats', 'Chats with an answer this month'], ['Turns', 'Answers this month']],
      users
    ),
    el('p', { class: 'admin-note' }, [`Highlighted: past ${spend.threshold.formatted} today.`]),
    el('h3', {}, ['Last 30 days']),
    chart(spend.daily),
    el('div', { class: 'admin-columns' }, [
      shares('By feature this month', spend.by_feature, FEATURE_LABELS),
      shares('By model this month', spend.by_model, {}),
    ]),
  ]);
}

function agentsSection(agents: AdminOverview['agents']): HTMLElement {
  const failures = agents.recent_failures.map((f) =>
    el('li', {}, [
      el('strong', {}, [f.agent_name]),
      ` (${f.user_name}), ${dateTime(f.started_at)}`,
      el('br'),
      el('span', { class: 'admin-error-text' }, [f.error]),
    ])
  );
  return section('Agents', [
    el('div', { class: 'admin-stats' }, [
      stat('Runs (7 days)', String(agents.runs_7d)),
      stat('Failed', String(agents.failed_7d), agents.failed_7d ? ' admin-stat-warn' : ''),
      stat('Waiting for approval', String(agents.pending_approvals)),
    ]),
    failures.length > 0 && el('h3', {}, ['Latest failures']),
    failures.length > 0 && el('ul', { class: 'admin-failures' }, failures),
  ]);
}

function searchSection(search: AdminOverview['search']): HTMLElement {
  const rows = search.providers.map((p) => {
    const usage = p.quota === null || p.quota === undefined ? 'unmetered' : `${p.used} / ${p.quota}`;
    const state = !p.configured ? 'no key' : p.available ? 'available' : 'out of service';
    return el('tr', { 'data-provider': p.provider }, [el('td', {}, [p.provider]), el('td', {}, [usage]), el('td', {}, [state])]);
  });
  return section('Web search this period', [
    search.degraded_today &&
      el('p', { class: 'admin-search-degraded' }, ['Search fell back to the free provider today.']),
    table(['Provider', 'Used', 'Status'], rows),
  ]);
}

function qualitySection(quality: AdminOverview['quality']): HTMLElement {
  return section('Responses (7 days)', [
    el('div', { class: 'admin-stats' }, [
      stat('Turns', String(quality.turns_7d)),
      stat('Typical time', seconds(quality.median_ms)),
      stat('Slowest 5%', seconds(quality.p95_ms)),
      stat('With tool errors', `${(quality.tool_error_rate * 100).toFixed(1)}%`),
    ]),
  ]);
}

const BROWSER_ERROR_KINDS: Record<string, string> = {
  error: 'Uncaught',
  unhandled_rejection: 'Unhandled rejection',
  logged: 'Logged',
};

function browserError(e: AdminOverview['browser_errors'][number]): HTMLElement {
  const people = e.users === 1 ? '1 person' : `${e.users} people`;
  const meta = [
    BROWSER_ERROR_KINDS[e.kind] ?? e.kind,
    `${e.count}×`,
    people,
    `last ${dateTime(e.last_seen)}`,
    e.path ?? '',
    e.app_version ? `build ${e.app_version}` : '',
  ].filter(Boolean);
  return el('li', {}, [
    el('span', { class: 'admin-error-text' }, [e.message]),
    el('br'),
    el('span', { class: 'admin-browser-error-meta' }, [meta.join(' · ')]),
    !!e.stack && el('details', {}, [el('summary', {}, ['Stack']), el('pre', {}, [e.stack])]),
  ]);
}

function browserErrorsSection(errors: AdminOverview['browser_errors']): HTMLElement {
  return section('Browser errors (7 days)', [
    errors.length
      ? el('ul', { class: 'admin-failures admin-browser-errors' }, errors.map(browserError))
      : el('p', { class: 'admin-note' }, ['No browser errors in the last 7 days.']),
  ]);
}

type LayoutCheck = AdminOverview['layout_checks'][number];

// What each check means, and which way it failed (core/layout-checks.ts)
const LAYOUT_CHECKS: Record<string, { label: string; shapes: Record<string, string> }> = {
  composer_gap: { label: 'Composer off the keyboard', shapes: { gap: 'gap above it', overlap: 'covered by it' } },
  stranded_pan: {
    label: 'Page left scrolled',
    shapes: { 'keyboard-open': 'keyboard open', 'keyboard-closed': 'keyboard closed' },
  },
  inset_mismatch: {
    label: 'Keyboard space wrong',
    shapes: { stuck: 'left after closing', missing: 'missing', off: 'wrong size' },
  },
  anchor_drift: {
    label: 'Sent message moved',
    shapes: { 'keyboard-open': 'keyboard opening', 'keyboard-close': 'keyboard closing' },
  },
  scroll_bottom_miss: { label: 'Scroll to the end fell short', shapes: { short: '' } },
};

function layoutWhere(c: LayoutCheck): string {
  if (c.standalone_count === c.count) return 'home-screen app';
  if (c.standalone_count === 0) return 'browser tab';
  return `${c.standalone_count} in the app, ${c.count - c.standalone_count} in a tab`;
}

function layoutCheck(c: LayoutCheck): HTMLElement {
  const known = LAYOUT_CHECKS[c.invariant];
  const shape = known ? (known.shapes[c.shape] ?? c.shape) : c.shape;
  const meta = [
    `${c.count}×`,
    c.users === 1 ? '1 person' : `${c.users} people`,
    layoutWhere(c),
    c.ios_version ? `iOS ${c.ios_version}` : '',
    `last ${dateTime(c.last_seen)}`,
  ].filter(Boolean);
  const numbers = Object.entries(c.measurements)
    .map(([name, value]) => `${name} ${value}`)
    .join('\n');
  return el('li', { 'data-invariant': c.invariant }, [
    el('span', { class: 'admin-layout-name' }, [known?.label ?? c.invariant]),
    !!shape && ' ',
    !!shape && el('span', { class: 'admin-layout-shape' }, [shape]),
    el('br'),
    el('span', { class: 'admin-browser-error-meta' }, [meta.join(' · ')]),
    el('details', {}, [el('summary', {}, ['Latest numbers']), el('pre', {}, [numbers])]),
  ]);
}

/** Group checks by build (app version + [kbN] marker), newest build first. */
function byBuild(checks: AdminOverview['layout_checks']): LayoutCheck[][] {
  const builds = new Map<string, LayoutCheck[]>();
  for (const check of checks) {
    const key = `${check.app_version ?? ''}|${check.build_marker ?? ''}`;
    builds.set(key, [...(builds.get(key) ?? []), check]);
  }
  return [...builds.values()];
}

function layoutBuild(checks: LayoutCheck[], currentVersion: string | null | undefined): HTMLElement {
  const first = checks[0];
  const total = checks.reduce((sum, c) => sum + c.count, 0);
  const name = [first?.app_version ?? 'unknown build', first?.build_marker ?? ''].filter(Boolean).join(' · ');
  const deployed = !!first?.app_version && first.app_version === currentVersion;
  return el('div', { class: 'admin-layout-build' }, [
    el('h3', {}, [
      el('span', {}, [name]),
      deployed && el('span', { class: 'admin-layout-current' }, ['Deployed']),
      el('span', { class: 'admin-layout-total' }, [`${total}×`]),
    ]),
    el('ul', { class: 'admin-failures admin-layout-checks' }, checks.map(layoutCheck)),
  ]);
}

function layoutChecksSection(checks: AdminOverview['layout_checks'], currentVersion: string | null | undefined): HTMLElement {
  return section('Layout checks (7 days)', [
    ...(checks.length
      ? byBuild(checks).map((build) => layoutBuild(build, currentVersion))
      : [el('p', { class: 'admin-note' }, ['No layout check failed in the last 7 days.'])]),
    el('p', { class: 'admin-note' }, [
      'Phones and tablets check the keyboard and scroll layout as they are used; a check a build fails and the one before it did not is a regression.',
    ]),
  ]);
}

function systemSection(system: AdminOverview['system']): HTMLElement {
  const facts: [string, string][] = [
    ['Version', system.version ?? '-'],
    ['Database', megabytes(system.database_bytes)],
    ['File store', megabytes(system.files_bytes)],
    ['Last backup', dateTime(system.last_backup_at)],
    ['Latest migration', system.latest_migration ?? '-'],
    ['Users', String(system.users)],
  ];
  return section('System', [
    el('dl', { class: 'admin-facts' }, facts.flatMap(([k, v]) => [el('dt', {}, [k]), el('dd', {}, [v])])),
  ]);
}

/** The page body for an overview (exported for tests). */
export function renderAdminOverview(data: AdminOverview): HTMLElement[] {
  return [
    spendSection(data.spend),
    agentsSection(data.agents),
    searchSection(data.search),
    qualitySection(data.quality),
    browserErrorsSection(data.browser_errors),
    layoutChecksSection(data.layout_checks, data.system.version),
    systemSection(data.system),
    el('p', { class: 'admin-note' }, [`Updated ${dateTime(data.generated_at)}`]),
  ];
}

function onKeydown(e: KeyboardEvent): void {
  if (!page) return;
  if (e.key === 'Escape') {
    // Captured first and stopped: the page sits over everything, so no other
    // Escape handler (sidebar selection, popups) may act behind it
    e.preventDefault();
    e.stopPropagation();
    closeAdminPage();
  } else if (e.key === 'Tab') {
    trapTabKey(page, e);
  }
}

async function load(body: HTMLElement, options: AdminPageOptions): Promise<void> {
  body.innerHTML = '<p class="admin-loading">Loading…</p>';
  try {
    body.replaceChildren(...renderAdminOverview(await admin.getOverview()));
    const { onRunDeviceChecks } = options;
    if (onRunDeviceChecks) {
      const runChecks = (): void => {
        closeAdminPage();
        onRunDeviceChecks();
      };
      // Before the closing "Updated ..." note
      body.insertBefore(createDeviceChecksSection(runChecks), body.lastElementChild);
    }
  } catch (error) {
    log.error('Failed to load the admin overview', { error });
    body.innerHTML = '<p class="admin-error">The overview could not be loaded. Try again in a moment.</p>';
  }
}

/** Open the admin page over the app; Escape or Back closes it. */
export async function openAdminPage(options: AdminPageOptions = {}): Promise<void> {
  if (page) return;
  // The Admin entry lives in the user menu, which closes as the page opens
  returnFocusTo = document.getElementById('user-menu-btn');
  page = document.createElement('div');
  page.className = 'admin-page';
  page.setAttribute('role', 'dialog');
  page.setAttribute('aria-modal', 'true');
  page.setAttribute('aria-labelledby', 'admin-page-title');
  page.append(
    createElement('header', { class: 'admin-header' }, [
      createIconButton({ type: 'button', class: 'admin-back', 'aria-label': 'Back' }, CHEVRON_LEFT_ICON),
      createElement('h1', { id: 'admin-page-title' }, ['Admin']),
      createIconButton({ type: 'button', class: 'admin-refresh', 'aria-label': 'Refresh' }, REFRESH_ICON),
    ]),
    createElement('div', { class: 'admin-body' })
  );
  document.body.appendChild(page);
  document.addEventListener('keydown', onKeydown, { capture: true });
  const body = page.querySelector<HTMLElement>('.admin-body');
  page.querySelector('.admin-back')?.addEventListener('click', closeAdminPage);
  page.querySelector('.admin-refresh')?.addEventListener('click', () => {
    if (body) void load(body, options);
  });
  getFocusableElements(page)[0]?.focus();
  if (body) await load(body, options);
}

/** Close the admin page and return focus to where it was. */
export function closeAdminPage(): void {
  if (!page) return;
  document.removeEventListener('keydown', onKeydown, { capture: true });
  page.remove();
  page = null;
  returnFocusTo?.focus();
  returnFocusTo = null;
}
