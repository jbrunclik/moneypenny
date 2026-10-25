/**
 * Grounding footer/sheet copy: counts and singular/plural forms.
 */
import { describe, it, expect } from 'vitest';
import { groundingStrings } from '@/components/messages/grounding-strings';

const t = groundingStrings();

describe('grounding strings', () => {
  it('pluralizes "differs" by count', () => {
    expect(t.contradicted(1)).toBe('1 differs from the source');
    expect(t.contradicted(2)).toBe('2 differ from the source');
  });

  it('pluralizes pages in the sheet meta line', () => {
    expect(t.sheetMeta(1, 3, 4)).toBe('Compared with 1 page · 3 of 4 sourced');
    expect(t.sheetMeta(5, 0, 2)).toBe('Compared with 5 pages · 0 of 2 sourced');
  });

  it('formats the counters', () => {
    expect(t.ofSourced(3, 5)).toBe('3 of 5 claims from sources');
    expect(t.unsourced(2)).toBe('2 without a source');
    expect(t.partial(1)).toBe('1 partly sourced');
    expect(t.sourceNumber(4)).toBe('Source 4');
  });

  it('quotes the claim in the look-up message', () => {
    expect(t.lookUpMessage('Prague has 1.4M people')).toBe('Look up and verify: Prague has 1.4M people');
  });

  it('has a label for every verdict and a heading for every non-supported one', () => {
    expect(Object.keys(t.verdictLabels).sort()).toEqual(['contradicted', 'not_found', 'partial', 'supported']);
    expect(Object.keys(t.headings).sort()).toEqual(['contradicted', 'not_found', 'partial']);
  });
});
