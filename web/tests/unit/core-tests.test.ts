/**
 * Rule T8 (frontend half): every `src/core/**` module ships with a test.
 *
 * A core module counts as tested when a unit or component test imports it at
 * runtime - a static import or an `await import()`. A `vi.mock()` of it
 * doesn't count (that replaces it), nor does a type-only import. The backend
 * half (route modules) is `tests/unit/test_route_tests.py`.
 *
 * `core-tests.baseline.json` lists the modules without a test when the rule
 * was added (Oct 26 2026); it only shrinks: tested one? Delete its entry.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import baseline from './core-tests.baseline.json';

const WEB = join(__dirname, '../..');
const CORE = join(WEB, 'src/core');
const TEST_DIRS = [join(WEB, 'tests/unit'), join(WEB, 'tests/component')];

function tsFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return tsFiles(path);
    return path.endsWith('.ts') && !path.endsWith('.d.ts') ? [path] : [];
  });
}

function compilerOptions(): ts.CompilerOptions {
  const configPath = join(WEB, 'tsconfig.json');
  const config = ts.readConfigFile(configPath, ts.sys.readFile).config as object;
  return ts.parseJsonConfigFileContent(config, ts.sys, dirname(configPath)).options;
}

function isTypeOnly(node: ts.ImportDeclaration): boolean {
  const clause = node.importClause;
  if (!clause) return false; // side-effect import
  if (clause.isTypeOnly) return true;
  const bindings = clause.namedBindings;
  return (
    !clause.name &&
    bindings !== undefined &&
    ts.isNamedImports(bindings) &&
    bindings.elements.length > 0 &&
    bindings.elements.every((e) => e.isTypeOnly)
  );
}

/** Module specifiers a test loads for real: static imports and `import('...')`. */
function runtimeSpecifiers(source: ts.SourceFile): string[] {
  const specifiers: string[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isImportDeclaration(node) &&
      ts.isStringLiteral(node.moduleSpecifier) &&
      !isTypeOnly(node)
    ) {
      specifiers.push(node.moduleSpecifier.text);
    } else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments[0] !== undefined &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      specifiers.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return specifiers;
}

function untestedCoreModules(): string[] {
  const options = compilerOptions();
  const tested = new Set<string>();
  for (const file of TEST_DIRS.flatMap(tsFiles)) {
    const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest);
    for (const specifier of runtimeSpecifiers(source)) {
      const resolved = ts.resolveModuleName(specifier, file, options, ts.sys).resolvedModule;
      if (resolved) tested.add(resolved.resolvedFileName);
    }
  }
  return tsFiles(CORE)
    .filter((file) => !tested.has(file))
    .map((file) => relative(CORE, file))
    .sort();
}

describe('core modules have tests (T8)', () => {
  const untested = untestedCoreModules();
  const allowed = new Set<string>(baseline);

  it('adds no core module without a test', () => {
    expect(untested.filter((m) => !allowed.has(m))).toEqual([]);
  });

  it('keeps the baseline free of modules that have a test now', () => {
    const current = new Set(untested);
    expect(baseline.filter((m) => !current.has(m))).toEqual([]);
  });
});
