/**
 * Rule S8 for the frontend: logs identify users by id and never carry an
 * email, a credential or a whole text. Client logs reach the server's
 * (client_errors, journal), so the same policy as test_log_fields.py
 * applies: this checks the keys of the context object passed to
 * log.debug/info/warn/error.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '../../src');
const LEVELS = new Set(['debug', 'info', 'warn', 'error']);
const LOGGERS = /^(log|logger)$/;
const DENIED = new Set([
  'email', 'password', 'token', 'accesstoken', 'refreshtoken', 'apikey', 'secret',
  'authorization', 'cookie', 'content', 'text', 'messagetext', 'history', 'messages',
]);
const DENIED_SUFFIXES = ['email', 'password', 'secret', 'apikey', 'accesstoken'];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return path.endsWith('.ts') && !path.endsWith('.d.ts') ? [path] : [];
  });
}

/** Every context key passed to a log call, as `file:line key`. */
function loggedKeys(): Array<{ where: string; key: string }> {
  const found: Array<{ where: string; key: string }> = [];
  for (const file of sourceFiles(SRC)) {
    const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
    const visit = (node: ts.Node): void => {
      if (
        ts.isCallExpression(node) &&
        ts.isPropertyAccessExpression(node.expression) &&
        LEVELS.has(node.expression.name.text) &&
        ts.isIdentifier(node.expression.expression) &&
        LOGGERS.test(node.expression.expression.text)
      ) {
        for (const arg of node.arguments) {
          if (!ts.isObjectLiteralExpression(arg)) continue;
          for (const prop of arg.properties) {
            const name = prop.name && (ts.isIdentifier(prop.name) || ts.isStringLiteral(prop.name)) ? prop.name.text : null;
            if (!name) continue;
            const line = source.getLineAndCharacterOfPosition(prop.getStart()).line + 1;
            found.push({ where: `${relative(SRC, file)}:${line}`, key: name });
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return found;
}

/** `todoist_email`, `userEmail` -> `todoistemail`, `useremail` */
const normalize = (key: string): string => key.toLowerCase().replace(/_/g, '');

describe('log fields (S8)', () => {
  const keys = loggedKeys();

  it('never logs an email, a credential or a whole text', () => {
    const offending = keys
      .filter(({ key }) => {
        const k = normalize(key);
        return DENIED.has(k) || DENIED_SUFFIXES.some((suffix) => k.endsWith(suffix));
      })
      .map(({ where, key }) => `${where} ${key}`);
    expect(offending, 'log a user id, a truncated excerpt or a length instead').toEqual([]);
  });

  it('sees the log calls (guards the scan itself)', () => {
    expect(keys.filter(({ key }) => key === 'conversationId').length).toBeGreaterThan(50);
  });
});
