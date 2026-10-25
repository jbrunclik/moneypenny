/**
 * Rule F1: no new runtime import cycles.
 *
 * A cycle makes module initialisation order matter (a `const` read before the
 * other module finished evaluating is `undefined`) and ties the layers
 * together. Type-only imports are erased at build time and are not counted.
 * The baseline lists every import edge that sat inside a cycle when this
 * guard was added (Oct 2026); it only shrinks. A new edge that closes a cycle
 * fails - point it down the layers instead (docs/conventions.md "Layers").
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import baseline from './import-cycles.baseline.json';

const WEB = join(__dirname, '../..');
const SRC = join(WEB, 'src');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return path.endsWith('.ts') && !path.endsWith('.d.ts') ? [path] : [];
  });
}

function isTypeOnly(node: ts.ImportDeclaration | ts.ExportDeclaration): boolean {
  if (ts.isExportDeclaration(node)) return node.isTypeOnly;
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

function runtimeImports(file: string, options: ts.CompilerOptions): string[] {
  const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest);
  const targets: string[] = [];
  for (const node of source.statements) {
    if (!(ts.isImportDeclaration(node) || ts.isExportDeclaration(node))) continue;
    if (!node.moduleSpecifier || !ts.isStringLiteral(node.moduleSpecifier) || isTypeOnly(node)) {
      continue;
    }
    const resolved = ts.resolveModuleName(node.moduleSpecifier.text, file, options, ts.sys)
      .resolvedModule?.resolvedFileName;
    if (resolved?.startsWith(SRC) && !resolved.endsWith('.d.ts')) targets.push(resolved);
  }
  return targets;
}

function compilerOptions(): ts.CompilerOptions {
  const configPath = join(WEB, 'tsconfig.json');
  const config = ts.readConfigFile(configPath, ts.sys.readFile).config as object;
  return ts.parseJsonConfigFileContent(config, ts.sys, dirname(configPath)).options;
}

/** Tarjan's strongly connected components; returns each module's component id. */
function components(graph: Map<string, string[]>): Map<string, number> {
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const component = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  let next = 0;
  let count = 0;

  const visit = (node: string): void => {
    index.set(node, next);
    low.set(node, next);
    next++;
    stack.push(node);
    onStack.add(node);
    for (const target of graph.get(node) ?? []) {
      if (!index.has(target)) {
        visit(target);
        low.set(node, Math.min(low.get(node)!, low.get(target)!));
      } else if (onStack.has(target)) {
        low.set(node, Math.min(low.get(node)!, index.get(target)!));
      }
    }
    if (low.get(node) === index.get(node)) {
      let member: string;
      do {
        member = stack.pop()!;
        onStack.delete(member);
        component.set(member, count);
      } while (member !== node);
      count++;
    }
  };
  for (const node of graph.keys()) if (!index.has(node)) visit(node);
  return component;
}

function cycleEdges(): string[] {
  const options = compilerOptions();
  const graph = new Map(sourceFiles(SRC).map((f) => [f, runtimeImports(f, options)]));
  const component = components(graph);
  const name = (file: string): string => relative(SRC, file);
  const edges: string[] = [];
  for (const [from, targets] of graph) {
    for (const to of targets) {
      // Same component = the edge lies on a cycle (a self-import is one too)
      if (component.get(from) === component.get(to)) edges.push(`${name(from)} -> ${name(to)}`);
    }
  }
  return [...new Set(edges)].sort();
}

describe('import cycles (F1)', () => {
  const edges = cycleEdges();
  const allowed = new Set<string>(baseline);

  it('adds no import edge that closes a cycle', () => {
    expect(edges.filter((e) => !allowed.has(e))).toEqual([]);
  });

  it('keeps the baseline free of edges that no longer cycle', () => {
    // Fixed one? Delete it from import-cycles.baseline.json so it can't return
    const current = new Set(edges);
    expect(baseline.filter((e) => !current.has(e))).toEqual([]);
  });
});
