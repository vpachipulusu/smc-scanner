import { describe, expect, it } from 'vitest';
import {
  EXPORT_PAGE_SIZE,
  JOURNAL_CSV_COLUMNS,
  MAX_EXPORT_PAGES,
  entriesToCsv,
  journalCsvFileName,
} from '@/lib/journal/csv';
import { makeClosedEntry, makeEntry } from '../../helpers/journal-fixtures';

const lines = (csv: string) => csv.split('\r\n');

describe('constants', () => {
  it('pages at the API limit and caps the pages', () => {
    expect(EXPORT_PAGE_SIZE).toBe(100);
    expect(MAX_EXPORT_PAGES).toBe(100);
  });
});

describe('entriesToCsv', () => {
  it('writes a header and one CRLF line per entry', () => {
    const csv = entriesToCsv([makeClosedEntry({ id: 5, notes: 'ok' })]);
    const [header, line, end] = lines(csv);
    expect(header).toBe(JOURNAL_CSV_COLUMNS.join(','));
    expect(line).toBe(
      '5,EURUSD,1h,long,1.1,1.09,1.12,2,,,2026-10-20T10:00:00Z,2026-10-20T14:00:00Z,,ok'
    );
    expect(end).toBe('');
  });

  it('leaves R and exit blank for an open trade', () => {
    const cols = lines(entriesToCsv([makeEntry()]))[1].split(',');
    const at = (name: (typeof JOURNAL_CSV_COLUMNS)[number]) =>
      cols[JOURNAL_CSV_COLUMNS.indexOf(name)];
    expect(at('r')).toBe('');
    expect(at('exit')).toBe('');
  });

  it('neutralises formula prefixes in text cells', () => {
    const csv = entriesToCsv([
      makeEntry({ symbol: '=SUM(A1)', notes: '+cmd' }),
      makeEntry({ symbol: '-1', notes: '@x' }),
      makeEntry({ symbol: 'A', notes: '\tx' }),
      makeEntry({ symbol: 'B', notes: '\rx' }),
    ]);
    expect(csv).toContain("'=SUM(A1)");
    expect(csv).toContain("'+cmd");
    expect(csv).toContain("'-1");
    expect(csv).toContain("'@x");
    expect(csv).toContain("'\tx");
    expect(csv).toContain('"\'\rx"');
  });

  it('neutralises full-width triggers and invisible leading characters', () => {
    const csv = entriesToCsv([
      makeEntry({ symbol: '＝SUM(A1)', notes: '​=1+1' }),
      makeEntry({ symbol: '＠x', notes: '﻿-1' }),
    ]);
    expect(csv).toContain("'＝SUM(A1)");
    expect(csv).toContain("'​=1+1");
    expect(csv).toContain("'＠x");
    expect(csv).toContain("'﻿-1");
  });

  it('does not treat a negative number as a formula', () => {
    const csv = entriesToCsv([makeClosedEntry({ exit: 1.08, pnl_currency: -12.5 })]);
    expect(csv).toContain(',-12.5,');
    expect(csv).not.toContain("'-12.5");
  });

  it('quotes cells with commas, quotes or newlines', () => {
    const csv = entriesToCsv([makeEntry({ notes: 'a,"b"\nc' })]);
    expect(csv).toContain('"a,""b""\nc"');
  });

  it('writes only a header for no entries', () => {
    expect(entriesToCsv([])).toBe(`${JOURNAL_CSV_COLUMNS.join(',')}\r\n`);
  });

  it('blanks non-finite numbers and survives odd fields', () => {
    const odd = makeEntry({ entry: Number.NaN, notes: ['a'] as unknown as string });
    expect(() => entriesToCsv([odd])).not.toThrow();
    expect(lines(entriesToCsv([odd]))[1]).not.toContain('NaN');
  });
});

describe('journalCsvFileName', () => {
  it('stamps the file with the UTC time', () => {
    expect(journalCsvFileName(new Date('2026-10-20T12:30:05.123Z'))).toBe(
      'smc-journal-20261020T123005Z.csv'
    );
  });
});
