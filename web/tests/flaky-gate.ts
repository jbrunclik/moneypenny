/**
 * Flaky-test gate (T6, docs/conventions.md): a test that failed and then
 * passed on a CI retry fails the run unless `e2e/flaky-quarantine.json` names
 * it with the TODO entry tracking it. Retries keep a slow runner green; they
 * must not hide a race.
 *
 * Usage (CI, after a Playwright run with the JSON reporter):
 *   node tests/flaky-gate.ts e2e-results.json
 * Plain Node runs it (type stripping): keep to erasable TypeScript syntax.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

interface ReportTest {
  projectName: string;
  status: string;
}

interface ReportSpec {
  title: string;
  file: string;
  line: number;
  tests: ReportTest[];
}

interface ReportSuite {
  title: string;
  specs?: ReportSpec[];
  suites?: ReportSuite[];
}

/** The part of Playwright's JSON report the gate reads. */
export interface PlaywrightReport {
  suites?: ReportSuite[];
}

export interface Flake {
  file: string;
  line: number;
  title: string;
  project: string;
}

/** A known flake allowed to pass on retry while its TODO entry is open. */
export interface QuarantineEntry {
  file: string;
  title: string;
  /** Only this browser project; every project when absent. */
  project?: string;
  /** The TODO.md entry (or e2e-reliability.md section) that tracks it. */
  todo: string;
}

function collect(suites: ReportSuite[], flakes: Flake[]): void {
  for (const suite of suites) {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests) {
        if (test.status === 'flaky') {
          flakes.push({ file: spec.file, line: spec.line, title: spec.title, project: test.projectName });
        }
      }
    }
    collect(suite.suites ?? [], flakes);
  }
}

/** Tests that failed at least once and then passed on a retry. */
export function findFlakes(report: PlaywrightReport): Flake[] {
  const flakes: Flake[] = [];
  collect(report.suites ?? [], flakes);
  return flakes;
}

/** The flakes no quarantine entry covers (same file, exact title, matching project). */
export function unquarantined(flakes: Flake[], quarantine: QuarantineEntry[]): Flake[] {
  return flakes.filter(
    (flake) =>
      !quarantine.some(
        (entry) =>
          entry.file === flake.file &&
          entry.title === flake.title &&
          (entry.project === undefined || entry.project === flake.project)
      )
  );
}

function main(reportPath: string): number {
  const report = JSON.parse(readFileSync(reportPath, 'utf8')) as PlaywrightReport;
  const quarantinePath = new URL('./e2e/flaky-quarantine.json', import.meta.url);
  const quarantine = JSON.parse(readFileSync(quarantinePath, 'utf8')) as QuarantineEntry[];
  const flakes = findFlakes(report);
  const failing = unquarantined(flakes, quarantine);
  for (const flake of flakes) {
    const verdict = failing.includes(flake) ? 'FLAKY' : 'quarantined';
    console.log(`${verdict}: [${flake.project}] ${flake.file}:${flake.line} ${flake.title}`);
  }
  if (failing.length > 0) {
    console.log(
      `\n${failing.length} test(s) passed only on a retry. Fix the race, or add the test to ` +
        'web/tests/e2e/flaky-quarantine.json with the TODO entry tracking it (T6).'
    );
    return 1;
  }
  console.log(flakes.length === 0 ? 'No flaky tests.' : 'Only quarantined flakes.');
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const reportPath = process.argv[2];
  if (!reportPath) {
    console.error('usage: node tests/flaky-gate.ts <playwright-json-report>');
    process.exit(2);
  }
  process.exit(main(reportPath));
}
