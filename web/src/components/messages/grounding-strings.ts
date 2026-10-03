/** UI text for grounding annotations, in the answer's language (cs, else en). */
import type { ClaimVerdict } from '../../types/api';

export interface GroundingStrings {
  checking: string;
  ofSourced: (n: number, total: number) => string;
  unsourced: (n: number) => string;
  partial: (n: number) => string;
  contradicted: (n: number) => string;
  headings: Record<Exclude<ClaimVerdict, 'supported'>, string>;
  verdictLabels: Record<ClaimVerdict, string>;
  legacyReason: string;
  lookUp: string;
  lookUpMessage: (quote: string) => string;
  sheetTitle: string;
  sheetMeta: (pages: number, sourced: number, total: number) => string;
}

const CS: GroundingStrings = {
  checking: 'Ověřuji proti zdrojům…',
  ofSourced: (n, total) => `${n} z ${total} tvrzení ze zdrojů`,
  unsourced: (n) => `${n} bez zdroje`,
  partial: (n) => `${n} částečně`,
  contradicted: (n) => `${n} jinak než zdroj`,
  headings: { not_found: 'Ve zdrojích není', partial: 'Částečně ve zdrojích', contradicted: 'Zdroj uvádí jinak' },
  verdictLabels: { supported: 'ZDROJ', partial: 'ČÁSTEČNĚ', not_found: 'BEZ ZDROJE', contradicted: 'JINAK' },
  legacyReason: 'Nenašel jsem to ve stránkách, které jsem při odpovědi četl.',
  lookUp: 'Dohledat',
  lookUpMessage: (quote) => `Dohledej a ověř: ${quote}`,
  sheetTitle: 'Kontrola zdrojů',
  sheetMeta: (pages, sourced, total) =>
    `Porovnáno ${pages === 1 ? 's 1 stránkou' : `se ${pages} stránkami`} · ${sourced} z ${total} podloženo`,
};

const EN: GroundingStrings = {
  checking: 'Checking against sources…',
  ofSourced: (n, total) => `${n} of ${total} claims from sources`,
  unsourced: (n) => `${n} without a source`,
  partial: (n) => `${n} partly sourced`,
  contradicted: (n) => `${n} differ from the source`,
  headings: { not_found: 'Not in the sources', partial: 'Partly in the sources', contradicted: 'The source says otherwise' },
  verdictLabels: { supported: 'SOURCE', partial: 'PARTLY', not_found: 'NO SOURCE', contradicted: 'DIFFERS' },
  legacyReason: 'Not found in the pages I read for this answer.',
  lookUp: 'Look it up',
  lookUpMessage: (quote) => `Look up and verify: ${quote}`,
  sheetTitle: 'Source check',
  sheetMeta: (pages, sourced, total) =>
    `Compared with ${pages} ${pages === 1 ? 'page' : 'pages'} · ${sourced} of ${total} sourced`,
};

export function groundingStrings(language?: string): GroundingStrings {
  return language === 'cs' ? CS : EN;
}
