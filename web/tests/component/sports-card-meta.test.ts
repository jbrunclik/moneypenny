/**
 * The sports card's meta line (Nov 19 2026): "Last session 2d ago · 12
 * sessions" - the days the user wrote in the program's chat, and when the
 * coach last logged a session.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { createSportsProgramsElement } from '@/components/SportsDashboard';
import type { SportsProgram } from '@/types/api';

const NOW = new Date('2026-11-19T12:00:00Z');

function program(extra: Partial<SportsProgram>): SportsProgram {
  return {
    id: 'pushups',
    name: 'Push-ups',
    emoji: '💪',
    created_at: '2026-10-01T00:00:00Z',
    has_conversation: true,
    quick_actions: [],
    last_session_at: null,
    session_count: 0,
    ...extra,
  } as SportsProgram;
}

function meta(p: SportsProgram): string | null | undefined {
  const el = createSportsProgramsElement([p], vi.fn(), vi.fn(), vi.fn());
  return el.querySelector('.sports-card-meta')?.textContent;
}

afterEach(() => vi.useRealTimers());

describe('sports card meta line', () => {
  it('shows when the last session was and how many there were', () => {
    vi.useFakeTimers({ now: NOW });
    expect(meta(program({ last_session_at: '2026-11-17T10:00:00Z', session_count: 12 }))).toBe(
      'Last session 2d ago · 12 sessions'
    );
  });

  it('uses the singular and a fresh session reads "just now"', () => {
    vi.useFakeTimers({ now: NOW });
    expect(meta(program({ last_session_at: '2026-11-19T11:59:40Z', session_count: 1 }))).toBe(
      'Last session just now · 1 session'
    );
  });

  it('a program with no sessions says so', () => {
    expect(meta(program({ has_conversation: false }))).toBe('No sessions yet');
  });
});
