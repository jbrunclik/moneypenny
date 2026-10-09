/**
 * A CSS class may be defined in only one stylesheet unless it is listed below.
 *
 * Styles are global, so two components picking the same class name silently
 * restyle each other (Jul 2026: `.memory-*` in popups.css and kv-store.css).
 * The allowlist holds the intentional cross-file layering that existed when
 * this guard was added: glass.css theming, shared button styles, layout
 * overrides. A new entry should be a deliberate override, not a name clash -
 * otherwise prefix the class with its component.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const STYLES_DIR = join(__dirname, '../../src/styles');

const ALLOWED_MULTI_FILE_CLASSES = new Set([
  'action-sheet',
  'agent-editor',
  'approval-description',
  'approval-tool',
  'btn',
  'btn-icon',
  'chat-header',
  'conversation-archive',
  'conversation-delete',
  'conversation-rename',
  'info-popup-content',
  'input-area',
  'input-container',
  'input-wrapper',
  'language-add-btn',
  'language-modal',
  'message-actions-overflow',
  'message-continue-btn',
  'message-copy-btn',
  'message-cost-btn',
  'message-delete-btn',
  'message-edit-btn',
  'message-imagegen-btn',
  'message-regenerate-btn',
  'message-save-quick-action-btn',
  'message-sources-btn',
  'message-speak-btn',
  'mobile-header',
  'modal',
  'model-dropdown',
  'qa-editor',
  'scroll-to-bottom',
  'sidebar',
  'sports-add-btn',
  'sports-modal',
  'toast',
]);

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return cssFiles(path);
    return name.endsWith('.css') ? [path] : [];
  });
}

/** Classes that START a selector (".foo .bar" defines foo, not bar). */
function definedClasses(css: string): Set<string> {
  const classes = new Set<string>();
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const [, selectorList] of withoutComments.matchAll(/([^{}]+)\{/g)) {
    for (const selector of selectorList.split(',')) {
      const match = selector.trim().match(/^\.([a-zA-Z][\w-]*)/);
      if (match) classes.add(match[1]);
    }
  }
  return classes;
}

describe('CSS class collisions', () => {
  it('defines each class in a single stylesheet unless allowlisted', () => {
    const filesByClass = new Map<string, string[]>();
    for (const file of cssFiles(STYLES_DIR)) {
      for (const cls of definedClasses(readFileSync(file, 'utf8'))) {
        filesByClass.set(cls, [...(filesByClass.get(cls) ?? []), relative(STYLES_DIR, file)]);
      }
    }
    const collisions = [...filesByClass.entries()]
      .filter(([cls, files]) => files.length > 1 && !ALLOWED_MULTI_FILE_CLASSES.has(cls))
      .map(([cls, files]) => `.${cls}: ${files.join(', ')}`);
    expect(collisions).toEqual([]);
  });

  it('keeps the allowlist free of classes that no longer span files', () => {
    const filesByClass = new Map<string, number>();
    for (const file of cssFiles(STYLES_DIR)) {
      for (const cls of definedClasses(readFileSync(file, 'utf8'))) {
        filesByClass.set(cls, (filesByClass.get(cls) ?? 0) + 1);
      }
    }
    const stale = [...ALLOWED_MULTI_FILE_CLASSES].filter((cls) => (filesByClass.get(cls) ?? 0) < 2);
    expect(stale).toEqual([]);
  });
});
