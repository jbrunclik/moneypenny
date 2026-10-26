/**
 * Rule F2: module-level `let` only for UI-ephemeral state.
 *
 * App state belongs in the store, where every change goes through a slice
 * action and sync, tests and other views see it. A module-level `let` is fine
 * for what only this module's UI wiring uses:
 * - a handle, recognised by its declared type (HANDLE_TYPE): a timer, an
 *   observer, an AbortController, a DOM element, a callback or cleanup
 *   function, an in-flight promise;
 * - other module-local UI state (a gesture's progress, a request-race token,
 *   an init-once flag), marked in place by a comment containing `(F2)` that
 *   says why it isn't store state. One marker covers the `let`s directly
 *   after it (comments between them are fine; any other statement ends it).
 * Every other module-level `let` fails: put the value in the store, or mark it.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '../../src');

// Timers, observers, abort controllers, DOM elements, speech sessions,
// functions (callbacks, cleanups, injected dependencies) and promises
const HANDLE_TYPE =
  /=>|ReturnType<typeof set(?:Timeout|Interval)>|\b(?:AbortController|\w*Observer|HTML\w*Element|Element|SpeechRecognition|Promise)\b/;
const MARKER = /\(F2\)/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return path.endsWith('.ts') && !path.endsWith('.d.ts') ? [path] : [];
  });
}

function hasMarker(text: string, node: ts.Node): boolean {
  const comments = ts.getLeadingCommentRanges(text, node.getFullStart()) ?? [];
  return comments.some((c) => MARKER.test(text.slice(c.pos, c.end)));
}

/** Module-level `let` bindings that are neither a handle nor marked, as `file:line name`. */
function unmarkedLets(file: string): string[] {
  const text = readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const found: string[] = [];
  let covered = false;
  for (const node of source.statements) {
    const isLet = ts.isVariableStatement(node) && Boolean(node.declarationList.flags & ts.NodeFlags.Let);
    if (!isLet) {
      covered = false;
      continue;
    }
    covered = covered || hasMarker(text, node);
    if (covered) continue;
    for (const decl of node.declarationList.declarations) {
      const type = decl.type?.getText(source) ?? '';
      if (HANDLE_TYPE.test(type)) continue;
      const line = source.getLineAndCharacterOfPosition(decl.getStart()).line + 1;
      found.push(`${relative(SRC, file)}:${line} ${decl.name.getText(source)}`);
    }
  }
  return found;
}

describe('module-level state (F2)', () => {
  it('keeps app state out of module-level lets', () => {
    const unmarked = sourceFiles(SRC).flatMap(unmarkedLets);
    expect(unmarked, 'move it to the store, or mark why it is module-local UI state with (F2)').toEqual([]);
  });

  it('recognises handles by type and honours the marker', () => {
    expect(HANDLE_TYPE.test('(() => void) | null')).toBe(true);
    expect(HANDLE_TYPE.test('Promise<void> | null')).toBe(true);
    expect(HANDLE_TYPE.test('ReturnType<typeof setTimeout> | null')).toBe(true);
    expect(HANDLE_TYPE.test('HTMLDivElement | null')).toBe(true);
    expect(HANDLE_TYPE.test('string | null')).toBe(false);
    expect(HANDLE_TYPE.test('GalleryItem[]')).toBe(false);
  });
});
