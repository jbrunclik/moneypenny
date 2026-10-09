/** UI text for grounding annotations (the UI is English; answers may be in any language). */
import type { ClaimVerdict } from '../../types/api';

export interface GroundingStrings {
  checking: string;
  ofSourced: (n: number, total: number) => string;
  unsourced: (n: number) => string;
  partial: (n: number) => string;
  contradicted: (n: number) => string;
  headings: Record<Exclude<ClaimVerdict, 'supported'>, string>;
  verdictLabels: Record<ClaimVerdict, string>;
  defaultReason: string;
  lookUp: string;
  lookedUpBelow: string;
  lookUpMessage: (quote: string) => string;
  sheetTitle: string;
  sourceNumber: (n: number) => string;
  sheetMeta: (pages: number, sourced: number, total: number) => string;
}

const EN: GroundingStrings = {
  checking: 'Checking against sources…',
  ofSourced: (n, total) => `${n} of ${total} claims from sources`,
  unsourced: (n) => `${n} without a source`,
  partial: (n) => `${n} partly sourced`,
  contradicted: (n) => `${n} ${n === 1 ? 'differs' : 'differ'} from the source`,
  headings: { not_found: 'Not in the sources', partial: 'Partly in the sources', contradicted: 'The source says otherwise' },
  verdictLabels: { supported: 'SOURCE', partial: 'PARTLY', not_found: 'NO SOURCE', contradicted: 'DIFFERS' },
  defaultReason: 'Not found in the pages I read for this answer.',
  lookUp: 'Look it up',
  lookedUpBelow: 'Looked up below ↓',
  lookUpMessage: (quote) => `Look up and verify: ${quote}`,
  sheetTitle: 'Source check',
  sourceNumber: (n) => `Source ${n}`,
  sheetMeta: (pages, sourced, total) =>
    `Compared with ${pages} ${pages === 1 ? 'page' : 'pages'} · ${sourced} of ${total} sourced`,
};

export function groundingStrings(): GroundingStrings {
  return EN;
}
