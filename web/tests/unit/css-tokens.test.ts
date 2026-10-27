/**
 * Rule F7: CSS uses the tokens from `styles/variables.css`.
 *
 * - No hex, `rgb()` or `hsl()` colour outside variables.css: a literal can't
 *   follow the light theme and drifts from the palette.
 * - A global stacking layer takes its z-index from a `--z-*` token. Small
 *   values (-1 to 10) only order siblings inside one component and stay
 *   literal.
 * - A class's own rules live in one stylesheet. Its own rules are the
 *   selectors that style the element itself: `.kv-entry`, `.kv-entry:hover`,
 *   `.kv-entry.active`. A context rule (`.kv-store-header .btn-refresh`)
 *   belongs to the context's stylesheet and doesn't count. Styles are global,
 *   so two stylesheets styling one class restyle each other (Jul 2026:
 *   `.memory-*` in popups.css and kv-store.css; Oct 2026: agents.css restyled
 *   every `.btn-icon` in the app). layout.css (where the app shell places each
 *   component), glass.css (the glass material) and mobile-sheets.css (mobile
 *   bottom sheets) are layers over every component, so they don't count.
 *
 * Each list is empty since Oct 27 2026 and stays empty.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '../../src');
const TOKENS_FILE = 'styles/variables.css';
const LAYER_FILES = new Set([
  'styles/layout.css',
  'styles/components/glass.css',
  'styles/components/mobile-sheets.css',
]);
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

/** A selector list split at its top-level commas (not those inside `:is()`). */
function selectors(list: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = '';
  for (const char of list) {
    if (char === '(' || char === '[') depth += 1;
    if (char === ')' || char === ']') depth -= 1;
    if (char === ',' && depth === 0) {
      parts.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  return [...parts, current];
}

/** The class a selector styles itself (`.btn:hover` -> btn), or null for a
 * context rule (`.header .btn`) or one that doesn't start with a class. */
function ownClass(selector: string): string | null {
  const trimmed = selector.trim();
  const flat = trimmed.replace(/\((?:[^()]|\([^()]*\))*\)/g, '');
  if (/[\s>+~]/.test(flat)) return null;
  return trimmed.match(/^\.([a-zA-Z][\w-]*)/)?.[1] ?? null;
}

/** `class: stylesheet` for each class whose own rules span stylesheets. */
function spreadClasses(): string[] {
  const filesByClass = new Map<string, Set<string>>();
  for (const { name, css } of stylesheets) {
    if (LAYER_FILES.has(name)) continue;
    for (const [, list = ''] of css.matchAll(/([^{}@;]+)\{/g)) {
      for (const selector of selectors(list)) {
        const cls = ownClass(selector);
        if (cls) filesByClass.set(cls, (filesByClass.get(cls) ?? new Set()).add(name));
      }
    }
  }
  return [...filesByClass.entries()]
    .filter(([, files]) => files.size > 1)
    .flatMap(([cls, files]) => [...files].map((file) => `${cls}: ${file}`))
    .sort();
}

describe('CSS tokens (F7)', () => {
  it('has no colour literals outside variables.css', () => {
    expect(colorLiterals()).toEqual([]);
  });

  it('takes global z-indexes from tokens', () => {
    expect(zIndexLiterals()).toEqual([]);
  });

  it("keeps each class's own rules in one stylesheet", () => {
    expect(spreadClasses()).toEqual([]);
  });
});
