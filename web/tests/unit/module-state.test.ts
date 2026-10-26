/**
 * Rule F2: module-level `let` only for UI-ephemeral handles.
 *
 * App state belongs in the store, where every change goes through a slice
 * action and sync, tests and other views see it. A module-level `let` is fine
 * for a handle that only this module's UI wiring uses: a timer, an observer, an
 * AbortController, a DOM element. Those are recognised by their declared type
 * (HANDLE_TYPE) and not counted. Every other module-level `let` is counted per
 * file against module-state.baseline.json (Oct 2026), which only shrinks: a
 * new one fails - put the value in the store, or type it as the handle it is.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import baseline from './module-state.baseline.json';

const SRC = join(__dirname, '../../src');

// Timers, observers, abort controllers, DOM elements and speech sessions
const HANDLE_TYPE =
  /\b(?:ReturnType<typeof (?:setTimeout|setInterval)>|AbortController|\w*Observer|HTML\w*Element|Element|SpeechRecognition)\b/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return path.endsWith('.ts') && !path.endsWith('.d.ts') ? [path] : [];
  });
}

/** Module-level `let` bindings that are not typed as a UI handle. */
function stateLets(file: string): number {
  const text = readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest);
  let count = 0;
  for (const node of source.statements) {
    if (!ts.isVariableStatement(node)) continue;
    if (!(node.declarationList.flags & ts.NodeFlags.Let)) continue;
    for (const decl of node.declarationList.declarations) {
      const type = decl.type?.getText(source) ?? '';
      if (!HANDLE_TYPE.test(type)) count++;
    }
  }
  return count;
}

function counts(): Record<string, number> {
  const result: Record<string, number> = {};
  for (const file of sourceFiles(SRC)) {
    const n = stateLets(file);
    if (n > 0) result[relative(SRC, file)] = n;
  }
  return result;
}

describe('module-level state (F2)', () => {
  const current = counts();
  const allowed: Record<string, number> = baseline;

  it('adds no module-level let beyond the baseline', () => {
    const over = Object.entries(current)
      .filter(([file, n]) => n > (allowed[file] ?? 0))
      .map(([file, n]) => `${file}: ${n} (baseline ${allowed[file] ?? 0})`);
    expect(over).toEqual([]);
  });

  it('keeps the baseline at the current counts', () => {
    // Removed some? Lower module-state.baseline.json so they can't return
    const under = Object.entries(allowed)
      .filter(([file, n]) => (current[file] ?? 0) < n)
      .map(([file, n]) => `${file}: ${current[file] ?? 0} (baseline ${n})`);
    expect(under).toEqual([]);
  });
});
