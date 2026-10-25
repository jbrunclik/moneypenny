/**
 * Admin page (S12): a full-screen read-only overview for the accounts in
 * ADMIN_EMAILS - spend, agent health, web-search quotas, response quality and
 * system facts. Names and numbers only; the backend never sends conversation
 * titles or content.
 */
import { admin } from '../api/admin';
import type { AdminOverview } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { getFocusableElements, trapTabKey } from '../utils/focus-trap';
import { CHEVRON_LEFT_ICON, REFRESH_ICON } from '../utils/icons';
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

function section(title: string, body: string): string {
  return `<section class="admin-section"><h2>${escapeHtml(title)}</h2>${body}</section>`;
}

function renderChart(daily: Spend['daily']): string {
  const max = Math.max(...daily.map((d) => d.amount.usd), 0);
  const barWidth = (CHART_WIDTH - CHART_GAP * (daily.length - 1)) / daily.length;
  const bars = daily
    .map((day, i) => {
      const height = max > 0 ? Math.round((day.amount.usd / max) * CHART_HEIGHT) : 0;
      const x = (i * (barWidth + CHART_GAP)).toFixed(1);
      const label = `${day.date}: ${day.amount.formatted}`;
      return `<rect x="${x}" y="${CHART_HEIGHT - height}" width="${barWidth.toFixed(1)}" height="${height}"><title>${escapeHtml(label)}</title></rect>`;
    })
    .join('');
  return `<svg class="admin-chart" viewBox="0 0 ${CHART_WIDTH} ${CHART_HEIGHT}" preserveAspectRatio="none" role="img" aria-label="Spend over the last 30 days">${bars}</svg>`;
}

function renderShares(title: string, shares: Spend['by_feature'], labels: Record<string, string>): string {
  const rows = shares
    .map((s) => `<li><span>${escapeHtml(labels[s.name] ?? s.name)}</span><span>${escapeHtml(s.amount.formatted)}</span></li>`)
    .join('');
  return `<div class="admin-shares"><h3>${escapeHtml(title)}</h3><ul>${rows}</ul></div>`;
}

function renderSpend(spend: Spend): string {
  const users = spend.users
    .map(
      (u) => `<tr class="admin-user-row${u.over_threshold ? ' admin-over-threshold' : ''}">
        <td>${escapeHtml(u.name)}</td><td>${escapeHtml(u.today.formatted)}</td><td>${escapeHtml(u.month.formatted)}</td></tr>`
    )
    .join('');
  return section(
    'Spend',
    `<div class="admin-stats">
      <div class="admin-stat admin-spend-today"><span>Today</span><strong>${escapeHtml(spend.today.formatted)}</strong></div>
      <div class="admin-stat"><span>This month</span><strong>${escapeHtml(spend.month.formatted)}</strong></div>
    </div>
    <table class="admin-table"><thead><tr><th>Person</th><th>Today</th><th>This month</th></tr></thead><tbody>${users}</tbody></table>
    <p class="admin-note">Highlighted: past ${escapeHtml(spend.threshold.formatted)} today.</p>
    <h3>Last 30 days</h3>${renderChart(spend.daily)}
    <div class="admin-columns">${renderShares('By feature this month', spend.by_feature, FEATURE_LABELS)}${renderShares('By model this month', spend.by_model, {})}</div>`
  );
}

function renderAgents(agents: AdminOverview['agents']): string {
  const failures = agents.recent_failures
    .map(
      (f) => `<li><strong>${escapeHtml(f.agent_name)}</strong> (${escapeHtml(f.user_name)}), ${escapeHtml(dateTime(f.started_at))}<br><span class="admin-error-text">${escapeHtml(f.error)}</span></li>`
    )
    .join('');
  return section(
    'Agents',
    `<div class="admin-stats">
      <div class="admin-stat"><span>Runs (7 days)</span><strong>${agents.runs_7d}</strong></div>
      <div class="admin-stat${agents.failed_7d ? ' admin-stat-warn' : ''}"><span>Failed</span><strong>${agents.failed_7d}</strong></div>
      <div class="admin-stat"><span>Waiting for approval</span><strong>${agents.pending_approvals}</strong></div>
    </div>
    ${failures ? `<h3>Latest failures</h3><ul class="admin-failures">${failures}</ul>` : ''}`
  );
}

function renderSearch(search: AdminOverview['search']): string {
  const rows = search.providers
    .map((p) => {
      const usage = p.quota === null || p.quota === undefined ? 'unmetered' : `${p.used} / ${p.quota}`;
      const state = !p.configured ? 'no key' : p.available ? 'available' : 'out of service';
      return `<tr data-provider="${escapeHtml(p.provider)}"><td>${escapeHtml(p.provider)}</td><td>${escapeHtml(usage)}</td><td>${escapeHtml(state)}</td></tr>`;
    })
    .join('');
  const degraded = search.degraded_today
    ? '<p class="admin-search-degraded">Search fell back to the free provider today.</p>'
    : '';
  return section(
    'Web search this period',
    `${degraded}<table class="admin-table"><thead><tr><th>Provider</th><th>Used</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`
  );
}

function renderQuality(quality: AdminOverview['quality']): string {
  return section(
    'Responses (7 days)',
    `<div class="admin-stats">
      <div class="admin-stat"><span>Turns</span><strong>${quality.turns_7d}</strong></div>
      <div class="admin-stat"><span>Typical time</span><strong>${seconds(quality.median_ms)}</strong></div>
      <div class="admin-stat"><span>Slowest 5%</span><strong>${seconds(quality.p95_ms)}</strong></div>
      <div class="admin-stat"><span>With tool errors</span><strong>${(quality.tool_error_rate * 100).toFixed(1)}%</strong></div>
    </div>`
  );
}

function renderSystem(system: AdminOverview['system']): string {
  const facts: [string, string][] = [
    ['Version', system.version ?? '-'],
    ['Database', megabytes(system.database_bytes)],
    ['File store', megabytes(system.files_bytes)],
    ['Last backup', dateTime(system.last_backup_at)],
    ['Latest migration', system.latest_migration ?? '-'],
    ['Users', String(system.users)],
  ];
  const rows = facts.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('');
  return section('System', `<dl class="admin-facts">${rows}</dl>`);
}

/** The page body for an overview (exported for tests). */
export function renderAdminOverview(data: AdminOverview): string {
  return [
    renderSpend(data.spend),
    renderAgents(data.agents),
    renderSearch(data.search),
    renderQuality(data.quality),
    renderSystem(data.system),
    `<p class="admin-note">Updated ${escapeHtml(dateTime(data.generated_at))}</p>`,
  ].join('');
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

async function load(body: HTMLElement): Promise<void> {
  body.innerHTML = '<p class="admin-loading">Loading…</p>';
  try {
    body.innerHTML = renderAdminOverview(await admin.getOverview());
  } catch (error) {
    log.error('Failed to load the admin overview', { error });
    body.innerHTML = '<p class="admin-error">The overview could not be loaded. Try again in a moment.</p>';
  }
}

/** Open the admin page over the app; Escape or Back closes it. */
export async function openAdminPage(): Promise<void> {
  if (page) return;
  // The Admin entry lives in the user menu, which closes as the page opens
  returnFocusTo = document.getElementById('user-menu-btn');
  page = document.createElement('div');
  page.className = 'admin-page';
  page.setAttribute('role', 'dialog');
  page.setAttribute('aria-modal', 'true');
  page.setAttribute('aria-labelledby', 'admin-page-title');
  page.innerHTML = `
    <header class="admin-header">
      <button type="button" class="admin-back" aria-label="Back">${CHEVRON_LEFT_ICON}</button>
      <h1 id="admin-page-title">Admin</h1>
      <button type="button" class="admin-refresh" aria-label="Refresh">${REFRESH_ICON}</button>
    </header>
    <div class="admin-body"></div>`;
  document.body.appendChild(page);
  document.addEventListener('keydown', onKeydown, { capture: true });
  const body = page.querySelector<HTMLElement>('.admin-body');
  page.querySelector('.admin-back')?.addEventListener('click', closeAdminPage);
  page.querySelector('.admin-refresh')?.addEventListener('click', () => {
    if (body) void load(body);
  });
  getFocusableElements(page)[0]?.focus();
  if (body) await load(body);
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
