/**
 * Tests for the sports and language program list pages.
 */
import { describe, it, expect } from 'vitest';
import { createSportsProgramsElement } from '@/components/SportsDashboard';
import { createLanguageProgramsElement } from '@/components/LanguageDashboard';
import type { LanguageProgram, SportsProgram } from '@/types/api';

const noop = (): void => {};

describe.each([
  ['sports', createSportsProgramsElement, '.sports-add-btn'],
  ['language', createLanguageProgramsElement, '.language-add-btn'],
] as const)('%s programs page', (_name, create, addSelector) => {
  it('offers ONE create button when empty - the empty-state CTA', () => {
    // The header "New Program" duplicated "Create your first program"
    const el = create([], noop, noop, noop);
    const buttons = el.querySelectorAll(addSelector);
    expect(buttons).toHaveLength(1);
    expect(buttons[0].classList.contains('program-empty-cta')).toBe(true);
  });

  it('keeps the header button once programs exist', () => {
    const program = { id: 'p1', name: 'Push-ups', emoji: '💪', created_at: '', updated_at: '' };
    const el = create([program as unknown as SportsProgram & LanguageProgram], noop, noop, noop);
    expect(el.querySelectorAll(`${addSelector}:not(.program-empty-cta)`)).toHaveLength(1);
  });
});
