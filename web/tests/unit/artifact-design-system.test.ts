/**
 * The artifact design system (src/artifact/design-system.css) stays tied to
 * the app's tokens and to what the agent is told it contains
 * (src/agent/prompt_texts/artifacts.py).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

const root = resolve(__dirname, '../../..');
const css = readFileSync(resolve(root, 'web/src/artifact/design-system.css'), 'utf8');
const appTokens = readFileSync(resolve(root, 'web/src/styles/variables.css'), 'utf8');
const guide = readFileSync(resolve(root, 'src/agent/prompt_texts/artifacts.py'), 'utf8');

const defined = new Set([...appTokens.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));

describe('artifact design system', () => {
  it('defines every --mp-* token from app tokens only', () => {
    const tokenDefs = [...css.matchAll(/(--mp-[\w-]+)\s*:\s*([^;]+);/g)];
    expect(tokenDefs.length).toBeGreaterThan(10);
    for (const [, name, value] of tokenDefs) {
      for (const [, used] of value.matchAll(/var\((--[\w-]+)/g)) {
        const ok = defined.has(used) || used.startsWith('--mp-');
        expect(ok, `${name} uses ${used}, not an app token`).toBe(true);
      }
    }
  });

  it('has no hex colours of its own', () => {
    expect(css.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
  });

  it('has every class and token the agent is told about', () => {
    for (const [, cls] of guide.matchAll(/\.(mp-[\w-]+)/g)) {
      expect(css, `missing .${cls}`).toContain(`.${cls}`);
    }
    const tokenList = guide.match(/var\(--mp-text\|([^)]+)\)/)?.[1] ?? '';
    for (const token of ['text', ...tokenList.split('|').map((t) => t.replace('--mp-', ''))]) {
      expect(css, `missing --mp-${token}`).toContain(`--mp-${token}:`);
    }
  });

  it('stacks rows and grids on narrow frames', () => {
    expect(css).toMatch(/@container[^{]*max-width:\s*480px/);
  });
});
