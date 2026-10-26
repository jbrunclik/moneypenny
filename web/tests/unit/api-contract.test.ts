/**
 * Every API client call hits an endpoint the server defines: each exported
 * client function is called with placeholder arguments against a recording
 * fetch, and the method + path it used must exist in the OpenAPI spec
 * (static/openapi.json, generated from the backend's routes). A renamed or
 * removed route, or a client typo, fails here instead of in production.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import * as admin from '@/api/admin';
import * as agents from '@/api/agents';
import * as app from '@/api/app';
import * as artifacts from '@/api/artifacts';
import * as auth from '@/api/auth';
import * as chat from '@/api/chat';
import * as clientErrors from '@/api/client-errors';
import * as conversations from '@/api/conversations';
import * as costs from '@/api/costs';
import * as files from '@/api/files';
import * as integrations from '@/api/integrations';
import * as kvStore from '@/api/kv-store';
import * as memories from '@/api/memories';
import * as planner from '@/api/planner';
import * as programs from '@/api/programs';
import * as push from '@/api/push';
import * as search from '@/api/search';
import * as settings from '@/api/settings';

const MODULES: Record<string, Record<string, unknown>> = {
  admin, agents, app, artifacts, auth, chat, clientErrors, conversations, costs, files,
  integrations, kvStore, memories, planner, programs, push, search, settings,
};

interface Spec {
  paths: Record<string, Record<string, unknown>>;
}
const spec = JSON.parse(readFileSync(resolve(__dirname, '../../../static/openapi.json'), 'utf8')) as Spec;

/** `/api/sports/{program}/reset` -> a regex matching any one path segment per parameter. */
const routes = Object.entries(spec.paths).map(([path, ops]) => ({
  path,
  pattern: new RegExp(`^${path.replace(/\{[^}]+\}/g, '[^/]+')}$`),
  methods: new Set(Object.keys(ops).map((m) => m.toUpperCase())),
}));

function defined(method: string, path: string): boolean {
  return routes.some((r) => r.pattern.test(path) && r.methods.has(method));
}

/** Every function on an exported client object (or exported directly). */
function clientFunctions(): Array<{ name: string; fn: (...args: unknown[]) => unknown }> {
  const out: Array<{ name: string; fn: (...args: unknown[]) => unknown }> = [];
  for (const [modName, mod] of Object.entries(MODULES)) {
    for (const [exportName, value] of Object.entries(mod)) {
      if (typeof value === 'function') {
        out.push({ name: `${modName}.${exportName}`, fn: value as (...args: unknown[]) => unknown });
      } else if (value && typeof value === 'object') {
        for (const [key, member] of Object.entries(value as Record<string, unknown>)) {
          if (typeof member === 'function') {
            out.push({ name: `${modName}.${exportName}.${key}`, fn: (member as (...a: unknown[]) => unknown).bind(value) });
          }
        }
      }
    }
  }
  return out;
}

const PLACEHOLDER_ARGS: unknown[] = ['x', 'y', 'z', 'w'];

describe('API client contract', () => {
  let requests: Array<{ method: string; path: string }>;

  beforeEach(() => {
    requests = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(typeof input === 'string' ? input : input.toString(), 'http://localhost');
        requests.push({ method: (init?.method ?? 'GET').toUpperCase(), path: url.pathname });
        return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('calls only endpoints the server defines', async () => {
    const unknown: string[] = [];
    let calledAny = 0;
    for (const { name, fn } of clientFunctions()) {
      requests = [];
      try {
        await Promise.race([
          Promise.resolve(fn(...PLACEHOLDER_ARGS)),
          new Promise((r) => setTimeout(r, 50)),
        ]);
      } catch {
        // Only the request matters: a placeholder answer may not parse
      }
      for (const req of requests) {
        calledAny++;
        if (!defined(req.method, req.path)) unknown.push(`${name}: ${req.method} ${req.path}`);
      }
    }
    expect(calledAny).toBeGreaterThan(50);
    expect(unknown).toEqual([]);
  });
});
