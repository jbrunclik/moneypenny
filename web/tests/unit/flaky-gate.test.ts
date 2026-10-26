/**
 * The CI flaky-test gate (T6): a test that only passed on a retry fails the
 * run unless the quarantine list names it, with the TODO entry that tracks it.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { findFlakes, unquarantined, type PlaywrightReport, type QuarantineEntry } from '../flaky-gate';

function report(specs: Array<{ file: string; title: string; status: string; project?: string }>): PlaywrightReport {
  return {
    suites: [
      {
        title: 'outer.spec.ts',
        suites: [
          {
            title: 'describe block',
            specs: specs.map((s) => ({
              title: s.title,
              file: s.file,
              line: 10,
              tests: [{ projectName: s.project ?? 'webkit', status: s.status }],
            })),
          },
        ],
      },
    ],
  };
}

describe('findFlakes', () => {
  it('lists tests that passed only on a retry', () => {
    const flakes = findFlakes(
      report([
        { file: 'chat/pin.spec.ts', title: 'pins', status: 'flaky' },
        { file: 'chat/send.spec.ts', title: 'sends', status: 'expected' },
        { file: 'chat/fail.spec.ts', title: 'fails', status: 'unexpected' },
      ])
    );
    expect(flakes).toEqual([{ file: 'chat/pin.spec.ts', line: 10, title: 'pins', project: 'webkit' }]);
  });

  it('finds specs in nested describe blocks and at the top level', () => {
    const nested = report([{ file: 'a.spec.ts', title: 'nested', status: 'flaky' }]);
    nested.suites?.push({
      title: 'b.spec.ts',
      specs: [{ title: 'top', file: 'b.spec.ts', line: 3, tests: [{ projectName: 'chromium', status: 'flaky' }] }],
    });
    expect(findFlakes(nested).map((f) => f.title)).toEqual(['nested', 'top']);
  });

  it('is empty for a report without suites', () => {
    expect(findFlakes({})).toEqual([]);
  });
});

describe('unquarantined', () => {
  const flake = { file: 'chat/pin.spec.ts', line: 10, title: 'pin moves a conversation', project: 'webkit' };

  it('lets a quarantined flake through', () => {
    const quarantine: QuarantineEntry[] = [
      { file: 'chat/pin.spec.ts', title: 'pin moves a conversation', todo: 'Open E2E flakes' },
    ];
    expect(unquarantined([flake], quarantine)).toEqual([]);
  });

  it('fails a flake that is not on the list', () => {
    expect(unquarantined([flake], [])).toEqual([flake]);
  });

  it('matches the title exactly, not as a prefix of another test', () => {
    const quarantine: QuarantineEntry[] = [{ file: 'chat/pin.spec.ts', title: 'pin moves', todo: 'x' }];
    expect(unquarantined([flake], quarantine)).toEqual([flake]);
  });

  it('scopes an entry to one browser when it names a project', () => {
    const quarantine: QuarantineEntry[] = [
      { file: 'chat/pin.spec.ts', title: 'pin moves a conversation', project: 'chromium', todo: 'x' },
    ];
    expect(unquarantined([flake], quarantine)).toEqual([flake]);
  });
});

describe('the quarantine list', () => {
  it('names only tests that exist, each with its tracking entry', () => {
    const testsDir = resolve(__dirname, '..');
    const entries = JSON.parse(readFileSync(resolve(testsDir, 'e2e/flaky-quarantine.json'), 'utf8')) as QuarantineEntry[];
    for (const entry of entries) {
      const source = readFileSync(resolve(testsDir, entry.file), 'utf8');
      // A template-literal title (`... (${name})`) is checked by its fixed prefix
      const fixed = entry.title.replace(/ \((desktop|mobile)\)$/, '');
      expect(source, `${entry.file}: "${entry.title}"`).toContain(fixed);
      expect(entry.todo.length, entry.title).toBeGreaterThan(0);
    }
  });
});
