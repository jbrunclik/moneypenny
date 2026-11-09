/**
 * App-sent messages (an artifact's or the claim card's button) are flagged
 * app_sent, so the server never takes them as the user's answer to a
 * proposal card (docs/features/proposals.md); typed ones are not flagged.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { chat } from '@/api/chat';

function capture(): () => Record<string, unknown> {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 'a1', content: 'ok' }), { status: 200 }));
  global.fetch = fetchMock as unknown as typeof fetch;
  return () => JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body)) as Record<string, unknown>;
}

describe('app_sent on chat requests', () => {
  afterEach(() => vi.restoreAllMocks());

  it('flags an app-sent message', async () => {
    const body = capture();
    await chat.sendBatch('c1', 'ok', undefined, undefined, undefined, false, null, 'u1', undefined, { appSent: true });
    expect(body().app_sent).toBe(true);
  });

  it('leaves a typed message unflagged', async () => {
    const body = capture();
    await chat.sendBatch('c1', 'ano', undefined, undefined, undefined, false, null, 'u1');
    expect(body()).not.toHaveProperty('app_sent');
  });
});
