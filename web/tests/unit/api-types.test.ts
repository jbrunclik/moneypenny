/**
 * Rule F6: API types come from the generated schemas, not hand-written copies.
 *
 * A hand-written object type (an `interface` or a `type X = { ... }` in
 * `src/`) whose property names match a schema in `generated-api.ts` is a
 * copy: it drifts from the spec (an optional field the server sends as
 * `null`, a field the spec added). Alias the schema instead, extended for
 * frontend-only fields - and where the spec is too loose, fix the spec.
 *
 * A copy is a type sharing at least MIN_SHARED property names with one
 * schema, covering MIN_OVERLAP of the larger of the two. `api-types.baseline.json`
 * lists the copies when the rule was added (Oct 26 2026); it only shrinks.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import baseline from './api-types.baseline.json';

const WEB = join(__dirname, '../..');
const SRC = join(WEB, 'src');
const GENERATED = join(SRC, 'types/generated-api.ts');
const MIN_SHARED = 3;
const MIN_OVERLAP = 0.75;

/** Types that look like a schema but are not API data (reason given) */
const NOT_API_TYPES: Record<string, string> = {
  'components/Lightbox.ts:GalleryItem': 'a resolved image of the open gallery, built from files',
};

function tsFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return tsFiles(path);
    return path.endsWith('.ts') && !path.endsWith('.d.ts') && path !== GENERATED ? [path] : [];
  });
}

function propertyNames(members: ts.NodeArray<ts.TypeElement>, source: ts.SourceFile): string[] {
  return members.flatMap((m) => (m.name ? [m.name.getText(source).replace(/['"]/g, '')] : []));
}

/** Property names of every schema in generated-api.ts (`components.schemas`) */
function generatedSchemas(): Map<string, Set<string>> {
  const source = ts.createSourceFile(GENERATED, readFileSync(GENERATED, 'utf8'), ts.ScriptTarget.Latest);
  const schemas = new Map<string, Set<string>>();
  source.forEachChild((node) => {
    if (!ts.isInterfaceDeclaration(node) || node.name.text !== 'components') return;
    for (const member of node.members) {
      if (!ts.isPropertySignature(member) || member.name.getText(source) !== 'schemas') continue;
      if (!member.type || !ts.isTypeLiteralNode(member.type)) continue;
      for (const schema of member.type.members) {
        if (!ts.isPropertySignature(schema) || !schema.type || !ts.isTypeLiteralNode(schema.type)) continue;
        schemas.set(schema.name.getText(source), new Set(propertyNames(schema.type.members, source)));
      }
    }
  });
  return schemas;
}

/** Hand-written object types in src/ that copy a generated schema, as `file:Name` */
function copiedSchemas(): string[] {
  const schemas = generatedSchemas();
  const copies: string[] = [];
  for (const file of tsFiles(SRC)) {
    const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest);
    const visit = (node: ts.Node): void => {
      let members: ts.NodeArray<ts.TypeElement> | undefined;
      if (ts.isInterfaceDeclaration(node)) members = node.members;
      else if (ts.isTypeAliasDeclaration(node) && ts.isTypeLiteralNode(node.type)) members = node.type.members;
      if (members && (ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node))) {
        const props = propertyNames(members, source);
        const isCopy = [...schemas.values()].some((schemaProps) => {
          const shared = props.filter((p) => schemaProps.has(p)).length;
          return shared >= MIN_SHARED && shared / Math.max(props.length, schemaProps.size) >= MIN_OVERLAP;
        });
        if (isCopy) copies.push(`${relative(SRC, file)}:${node.name.text}`);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return copies.filter((c) => !(c in NOT_API_TYPES)).sort();
}

describe('API types alias the generated schemas (F6)', () => {
  const copies = copiedSchemas();
  const allowed = new Set<string>(baseline);

  it('adds no hand-written copy of a generated schema', () => {
    expect(copies.filter((c) => !allowed.has(c))).toEqual([]);
  });

  it('keeps the baseline free of types that alias the spec now', () => {
    const current = new Set(copies);
    expect(baseline.filter((c) => !current.has(c))).toEqual([]);
  });

  it('reads the generated schemas', () => {
    // An empty map would pass the checks above while detecting nothing
    expect(generatedSchemas().get('AuthResponse')?.has('token')).toBe(true);
  });
});
