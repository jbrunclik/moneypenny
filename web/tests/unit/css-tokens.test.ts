/**
 * Rule F7: CSS uses the tokens from `styles/variables.css`.
 *
 * - No hex, `rgb()` or `hsl()` colour outside variables.css: a literal can't
 *   follow the light theme and drifts from the palette.
 * - A global stacking layer takes its z-index from a `--z-*` token. Small
 *   values (-1 to 10) only order siblings inside one component and stay
 *   literal.
 * - One stylesheet per component prefix (`.kv-*` lives in kv-store.css).
 *   glass.css and mobile-sheets.css are layers that restyle every component
 *   (the glass material, mobile bottom sheets), so they don't count.
 *
 * `css-tokens.baseline.json` lists what predates the rule (Oct 26 2026) and
 * only shrinks: fixed one? Delete its entry.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import baseline from './css-tokens.baseline.json';

const SRC = join(__dirname, '../../src');
const TOKENS_FILE = 'styles/variables.css';
const LAYER_FILES = new Set(['styles/components/glass.css', 'styles/components/mobile-sheets.css']);
const LOCAL_Z_INDEX_MAX = 10;
const COLOR_LITERAL = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\([^)]*\)/g;

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return cssFiles(path);
    return name.endsWith('.css') ? [path] : [];
  });
}

const stylesheets = cssFiles(SRC).map((file) => ({
  name: relative(SRC, file),
  css: readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''),
}));

/** Every `property: value` declaration (selectors like `a:hover {` end at the brace). */
function declarations(css: string): { property: string; value: string }[] {
  return [...css.matchAll(/([\w-]+)\s*:\s*([^;{}]+)/g)].map(([, property = '', value = '']) => ({
    property,
    value: value.replace(/\s+/g, ' ').trim(),
  }));
}

function colorLiterals(): string[] {
  return stylesheets
    .filter(({ name }) => name !== TOKENS_FILE)
    .flatMap(({ name, css }) =>
      declarations(css).flatMap(({ value }) =>
        [...value.matchAll(COLOR_LITERAL)].map(([literal]) => `${name}: ${literal}`),
      ),
    )
    .sort();
}

function zIndexLiterals(): string[] {
  return stylesheets
    .flatMap(({ name, css }) =>
      declarations(css)
        .filter(({ property, value }) => {
          if (property !== 'z-index' || value.includes('var(--z-')) return false;
          const local = /^-?\d+$/.test(value) && Math.abs(Number(value)) <= LOCAL_Z_INDEX_MAX;
          return !local && value !== 'auto';
        })
        .map(({ value }) => `${name}: ${value}`),
    )
    .sort();
}

/**
 * `prefix: stylesheet` for each stylesheet defining classes of a prefix
 * (`.kv-entry` -> kv) that more than one stylesheet defines.
 */
function sharedPrefixes(): string[] {
  const filesByPrefix = new Map<string, Set<string>>();
  for (const { name, css } of stylesheets) {
    if (LAYER_FILES.has(name)) continue;
    for (const [, selectorList = ''] of css.matchAll(/([^{}]+)\{/g)) {
      for (const selector of selectorList.split(',')) {
        const prefix = selector.trim().match(/^\.([a-zA-Z][a-zA-Z0-9]*)/)?.[1];
        if (prefix) filesByPrefix.set(prefix, (filesByPrefix.get(prefix) ?? new Set()).add(name));
      }
    }
  }
  return [...filesByPrefix.entries()]
    .filter(([, files]) => files.size > 1)
    .flatMap(([prefix, files]) => [...files].map((file) => `${prefix}: ${file}`))
    .sort();
}

/** Entries of `actual` beyond what `allowed` holds, counting duplicates. */
function beyond(actual: string[], allowed: string[]): string[] {
  const left = new Map<string, number>();
  for (const entry of allowed) left.set(entry, (left.get(entry) ?? 0) + 1);
  return actual.filter((entry) => {
    const count = left.get(entry) ?? 0;
    left.set(entry, count - 1);
    return count <= 0;
  });
}

describe('CSS tokens (F7)', () => {
  const checks = [
    ['colour literals', colorLiterals(), baseline.colors],
    ['z-index literals', zIndexLiterals(), baseline.zIndex],
    ['component prefixes spread over stylesheets', sharedPrefixes(), baseline.prefixes],
  ] as const;

  for (const [what, actual, allowed] of checks) {
    it(`adds no new ${what}`, () => {
      expect(beyond(actual, allowed)).toEqual([]);
    });

    it(`keeps the ${what} baseline free of fixed entries`, () => {
      // Fixed one? Delete it from css-tokens.baseline.json so it can't return
      expect(beyond(allowed, actual)).toEqual([]);
    });
  }
});
