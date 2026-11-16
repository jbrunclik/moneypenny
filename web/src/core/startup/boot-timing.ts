/**
 * How long this page load's startup took, reported once the app is ready:
 * slow opening was unmeasured, and a cached sidebar or lazy KaTeX gets
 * decided from these numbers (Nov 16 2026). Marks are ms since navigation
 * start; one report per load, signed in only, a failure is dropped.
 */
import { clientTiming, type ClientTimingReport } from '../../api/client-timing';
import { MOBILE_BREAKPOINT_PX } from '../../config';
import type { InitialRoute } from '../../router/deeplink';

type Stage = 'script' | 'auth' | 'data' | 'route' | 'ready';

// This load's stage marks
const marks: Partial<Record<Stage, number>> = {};
// UI-local (F2): whether this load already sent its report
let reported = false;
// UI-local (F2): the page went to the background before it was ready (a
// backgrounded phone reports minutes; such rows are left out of medians)
let hidden = false;
// UI-local (F2): the visibility listener is in place
let watching = false;

function noteHidden(): void {
  if (document.visibilityState === 'hidden' && !reported) hidden = true;
}

/** Record that startup reached a stage (the first time only). */
export function markBootStage(stage: Stage): void {
  marks[stage] ??= Math.round(performance.now());
  noteHidden();
  if (!watching) {
    watching = true;
    document.addEventListener('visibilitychange', noteHidden);
  }
}

/** Test hook: a fresh page load. */
export function _resetBootTiming(): void {
  for (const stage of Object.keys(marks) as Stage[]) delete marks[stage];
  reported = false;
  hidden = false;
}

/** The initial route as a short label ("conversation", "planner", "home"...). */
export function routeLabel(route: InitialRoute | null | undefined): string {
  if (!route) return 'home';
  if (route.conversationId) return 'conversation';
  const views: Array<[boolean, string]> = [
    [route.isPlanner, 'planner'],
    [route.isAgents, 'agents'],
    [route.isStorage, 'storage'],
    [route.isSports, 'sports'],
    [route.isLanguage, 'language'],
    [route.isArchive, 'archive'],
    [route.isTrash, 'trash'],
  ];
  return views.find(([on]) => on)?.[1] ?? 'home';
}

function navigationMarks(): Pick<ClientTimingReport['marks'], 'response_end_ms' | 'dom_content_loaded_ms'> {
  const [nav] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
  if (!nav) return { response_end_ms: null, dom_content_loaded_ms: null };
  return {
    response_end_ms: Math.round(nav.responseEnd),
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd) || null,
  };
}

function stageMarks(): ClientTimingReport['marks'] {
  return {
    ...navigationMarks(),
    script_ms: marks.script ?? null,
    auth_ms: marks.auth ?? null,
    data_ms: marks.data ?? null,
    route_ms: marks.route ?? null,
    ready_ms: marks.ready ?? null,
  };
}

function device(): Pick<ClientTimingReport, 'standalone' | 'viewport' | 'connection' | 'app_version'> {
  const connection = (navigator as Navigator & { connection?: { effectiveType?: string } }).connection;
  return {
    standalone: window.matchMedia?.('(display-mode: standalone)').matches ?? false,
    viewport: window.innerWidth < MOBILE_BREAKPOINT_PX ? 'mobile' : 'desktop',
    connection: connection?.effectiveType?.slice(0, 16) ?? null,
    app_version: document.getElementById('app')?.dataset.version ?? null,
  };
}

/** Send this load's report (once; the app is ready and signed in). */
export function reportBootTiming(route: InitialRoute | null | undefined): void {
  // Only a load that was signed in at boot: after a sign-in, the time spent
  // at the sign-in button is the person's, not startup's
  if (reported || marks.auth === undefined) return;
  reported = true;
  markBootStage('ready');
  const report: ClientTimingReport = {
    marks: stageMarks(),
    ...device(),
    route: routeLabel(route),
    hidden,
  };
  // Telemetry: a lost report is acceptable, a retried one would double-count
  clientTiming.report(report).catch(() => {});
}
