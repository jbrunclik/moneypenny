/**
 * Every custom property a stylesheet reads without a fallback must be defined.
 *
 * An undefined `var(--x)` silently falls back to the property's initial value
 * (Oct 2026: `--radius-xl` squared off the agent editor's corners, and
 * `--font-mono` dropped the monospace face in three places). Properties set
 * from TypeScript via `style.setProperty('--x', ...)` count as defined.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC_DIR = join(__dirname, '../../src');
const STYLES_DIR = join(SRC_DIR, 'styles');

function filesUnder(dir: string, ext: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return filesUnder(path, ext);
    return path.endsWith(ext) ? [path] : [];
  });
}

function definedProperties(): Set<string> {
  const defined = new Set<string>();
  for (const file of filesUnder(STYLES_DIR, '.css')) {
    for (const m of readFileSync(file, 'utf8').matchAll(/(--[\w-]+)\s*:/g)) defined.add(m[1]);
  }
  for (const file of filesUnder(SRC_DIR, '.ts')) {
    for (const m of readFileSync(file, 'utf8').matchAll(/setProperty\(\s*['"`](--[\w-]+)/g)) defined.add(m[1]);
  }
  return defined;
}

describe('CSS custom properties', () => {
  it('reads only defined properties when no fallback is given', () => {
    const defined = definedProperties();
    const undefinedUses: string[] = [];
    for (const file of filesUnder(STYLES_DIR, '.css')) {
      for (const m of readFileSync(file, 'utf8').matchAll(/var\(\s*(--[\w-]+)\s*\)/g)) {
        if (!defined.has(m[1])) undefinedUses.push(`${relative(STYLES_DIR, file)}: ${m[1]}`);
      }
    }
    expect(undefinedUses).toEqual([]);
  });
});
