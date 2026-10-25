/**
 * Rule F9: a button inside a form declares its type.
 *
 * A <button> without `type` is a submit button, so inside a <form> every
 * icon or "Cancel" button would submit it. The app has no forms today, which
 * is why most buttons omit the type; the first file that builds a form must
 * give each of its buttons one.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '../../src');
const FORM = /<form\b|createElement\(\s*['"]form['"]\s*\)/;
const UNTYPED_BUTTON = /<button\b(?![^>]*\btype=)/g;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return path.endsWith('.ts') ? [path] : [];
  });
}

function untypedButtonsInForms(files: Record<string, string>): string[] {
  return Object.entries(files)
    .filter(([, text]) => FORM.test(text))
    .flatMap(([name, text]) => [...text.matchAll(UNTYPED_BUTTON)].map(() => name));
}

describe('button types (F9)', () => {
  it('flags untyped buttons only in files that build a form', () => {
    expect(
      untypedButtonsInForms({
        'form.ts': '<form><button type="submit">Go</button><button>Oops</button></form>',
        'menu.ts': '<div><button class="icon"></button></div>',
      })
    ).toEqual(['form.ts']);
  });

  it('finds no untyped button in a file that builds a form', () => {
    const files = Object.fromEntries(
      sourceFiles(SRC).map((path) => [relative(SRC, path), readFileSync(path, 'utf8')])
    );
    expect(untypedButtonsInForms(files)).toEqual([]);
  });
});
