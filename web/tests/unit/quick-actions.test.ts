/**
 * Unit tests for quick-action message composition and bar visibility rules.
 */
import { describe, it, expect } from 'vitest';
import { composeQuickActionMessage, shouldShowQuickActionsBar } from '@/core/quick-actions';
import type { QuickAction } from '@/types/api';

const action: QuickAction = {
  id: 'log',
  emoji: '📊',
  label: 'Log & review',
  body: 'Assess today.  ',
  fields: ['Hang time (s)', 'Comments'],
};

describe('composeQuickActionMessage', () => {
  it('returns the trimmed body when there are no fields', () => {
    expect(composeQuickActionMessage({ ...action, fields: [] }, {})).toBe('Assess today.');
  });

  it('returns only the body when every field is empty or whitespace', () => {
    expect(composeQuickActionMessage(action, { 'Hang time (s)': '  ', Comments: '' })).toBe(
      'Assess today.'
    );
  });

  it('appends Label: value lines after a blank line, in field order', () => {
    const out = composeQuickActionMessage(action, {
      Comments: 'felt strong',
      'Hang time (s)': '54',
    });
    expect(out).toBe('Assess today.\n\nHang time (s): 54\nComments: felt strong');
  });

  it('omits empty fields but keeps the others', () => {
    const out = composeQuickActionMessage(action, { 'Hang time (s)': '', Comments: 'ok' });
    expect(out).toBe('Assess today.\n\nComments: ok');
  });

  it('indents continuation lines of multi-line values by two spaces', () => {
    const out = composeQuickActionMessage(action, { Comments: 'line one\nline two\n' });
    expect(out).toBe('Assess today.\n\nComments: line one\n  line two');
  });
});

describe('shouldShowQuickActionsBar', () => {
  it('desktop: always visible', () => {
    expect(
      shouldShowQuickActionsBar({ mobile: false, composerEmpty: false, streaming: true })
    ).toBe(true);
  });
  it('mobile: visible only when composer is empty and nothing streams', () => {
    expect(
      shouldShowQuickActionsBar({ mobile: true, composerEmpty: true, streaming: false })
    ).toBe(true);
    expect(
      shouldShowQuickActionsBar({ mobile: true, composerEmpty: false, streaming: false })
    ).toBe(false);
    expect(
      shouldShowQuickActionsBar({ mobile: true, composerEmpty: true, streaming: true })
    ).toBe(false);
  });
});
