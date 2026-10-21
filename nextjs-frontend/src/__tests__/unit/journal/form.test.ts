// @vitest-environment node
/** Journal form parsing, R-multiples, prefill and paging params. */
import { describe, expect, it } from 'vitest';
import {
  EMPTY_JOURNAL_VALUES,
  parseJournalForm,
  parseJournalId,
  readJournalValues,
  valuesFromEntry,
} from '@/lib/journal/form';
import { formatR, rMultiple } from '@/lib/journal/format';
import { JOURNAL_PAGE_SIZE, journalHref, parseJournalCursor } from '@/lib/journal/params';
import { buildLogTradeHref, parsePrefill } from '@/lib/journal/prefill';
import { makeAnalysis } from '../../helpers/fixtures';
import { makeClosedEntry, makeEntry } from '../../helpers/journal-fixtures';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const VALID = {
  symbol: 'EURUSD',
  timeframe: '1h',
  side: 'long',
  entry: '1.1000',
  stop: '1.0900',
  opened_at: '2026-10-20T10:00',
};

describe('parseJournalForm', () => {
  it('builds the API body for an open long trade', () => {
    const parsed = parseJournalForm(form(VALID));
    expect(parsed).toEqual({
      ok: true,
      body: {
        symbol: 'EURUSD',
        timeframe: '1h',
        side: 'long',
        entry: 1.1,
        stop: 1.09,
        exit: null,
        size: null,
        pnl_currency: null,
        opened_at: '2026-10-20T10:00:00Z',
        closed_at: null,
        notes: '',
        analysis_id: null,
      },
    });
  });

  it('accepts a closed short trade with every optional field', () => {
    const parsed = parseJournalForm(
      form({
        ...VALID,
        side: 'short',
        entry: '1.1',
        stop: '1.11',
        exit: '1.08',
        closed_at: '2026-10-20T12:30',
        size: '0.5',
        pnl_currency: '-12.5',
        notes: '  <b>note</b>  ',
        analysis_id: '42',
      })
    );
    expect(parsed).toMatchObject({
      ok: true,
      body: {
        side: 'short',
        exit: 1.08,
        closed_at: '2026-10-20T12:30:00Z',
        size: 0.5,
        pnl_currency: -12.5,
        notes: '<b>note</b>',
        analysis_id: 42,
      },
    });
  });

  it('requires a stop below entry for a long and above entry for a short', () => {
    expect(parseJournalForm(form({ ...VALID, stop: '1.1' }))).toMatchObject({
      ok: false,
      errors: { stop: expect.stringContaining('below') },
    });
    expect(parseJournalForm(form({ ...VALID, stop: '1.2' }))).toMatchObject({
      ok: false,
      errors: { stop: expect.stringContaining('below') },
    });
    expect(parseJournalForm(form({ ...VALID, side: 'short', stop: '1.0' }))).toMatchObject({
      ok: false,
      errors: { stop: expect.stringContaining('above') },
    });
  });

  it('rejects a stop that is too close to entry', () => {
    expect(parseJournalForm(form({ ...VALID, entry: '1000', stop: '999.9999999' }))).toMatchObject({
      ok: false,
      errors: { stop: expect.stringContaining('too close') },
    });
  });

  it.each([
    ['entry', 'abc'],
    ['entry', 'NaN'],
    ['entry', 'Infinity'],
    ['entry', '1e5'],
    ['entry', ''],
    ['entry', '0'],
    ['entry', '1000000000001'],
    ['stop', '-1'],
    ['stop', ''],
  ])('rejects %s = "%s" as not a usable price', (field, value) => {
    const parsed = parseJournalForm(form({ ...VALID, [field]: value }));
    expect(parsed.ok).toBe(false);
    expect(!parsed.ok && parsed.errors[field as 'entry']).toEqual(expect.any(String));
  });

  it('validates the choice fields, symbol and times', () => {
    const parsed = parseJournalForm(
      form({ symbol: 'bad symbol!', timeframe: '2h', side: 'up', entry: '1', stop: '0.5' })
    );
    expect(parsed).toMatchObject({
      ok: false,
      errors: {
        symbol: expect.any(String),
        timeframe: expect.any(String),
        side: expect.any(String),
        opened_at: expect.any(String),
      },
    });
    expect(parseJournalForm(form({ ...VALID, opened_at: '2026-02-30T10:00' })).ok).toBe(false);
  });

  it('requires exit and closed_at together, and a close not before the open', () => {
    expect(parseJournalForm(form({ ...VALID, exit: '1.2' }))).toMatchObject({
      ok: false,
      errors: { closed_at: expect.any(String) },
    });
    expect(parseJournalForm(form({ ...VALID, closed_at: '2026-10-20T12:00' }))).toMatchObject({
      ok: false,
      errors: { exit: expect.any(String) },
    });
    expect(
      parseJournalForm(form({ ...VALID, exit: '1.2', closed_at: '2026-10-19T12:00' }))
    ).toMatchObject({ ok: false, errors: { closed_at: expect.stringContaining('before') } });
  });

  it('needs a closed trade for a result in currency, and a positive size', () => {
    expect(parseJournalForm(form({ ...VALID, pnl_currency: '5' }))).toMatchObject({
      ok: false,
      errors: { pnl_currency: expect.any(String) },
    });
    expect(parseJournalForm(form({ ...VALID, size: '0' }))).toMatchObject({
      ok: false,
      errors: { size: expect.any(String) },
    });
  });

  it('limits notes and analysis ids', () => {
    expect(parseJournalForm(form({ ...VALID, notes: 'x'.repeat(2001) }))).toMatchObject({
      ok: false,
      errors: { notes: expect.any(String) },
    });
    expect(parseJournalForm(form({ ...VALID, analysis_id: '0' }))).toMatchObject({
      ok: false,
      errors: { analysis_id: expect.any(String) },
    });
  });

  it('returns the submitted values for redisplay', () => {
    const parsed = parseJournalForm(form({ ...VALID, entry: 'oops' }));
    expect(!parsed.ok && parsed.values.entry).toBe('oops');
    expect(!parsed.ok && parsed.values.symbol).toBe('EURUSD');
  });

  it('ignores fields outside the allow-list', () => {
    const parsed = parseJournalForm(form({ ...VALID, id: '9', is_admin: 'yes' }));
    expect(parsed.ok && Object.keys(parsed.body)).not.toContain('is_admin');
    expect(parsed.ok && Object.keys(parsed.body)).not.toContain('id');
  });
});

describe('form values', () => {
  it('reads blanks for missing and non-text fields', () => {
    const data = new FormData();
    data.append('symbol', new File(['x'], 'x.txt'));
    expect(readJournalValues(data)).toEqual({
      ...EMPTY_JOURNAL_VALUES,
      symbol: '',
      timeframe: '',
      side: '',
    });
  });

  it('turns a stored entry into form values', () => {
    expect(
      valuesFromEntry(makeClosedEntry({ size: 2, pnl_currency: 3, notes: 'n', analysis_id: 8 }))
    ).toEqual({
      symbol: 'EURUSD',
      timeframe: '1h',
      side: 'long',
      entry: '1.1',
      stop: '1.09',
      exit: '1.12',
      size: '2',
      pnl_currency: '3',
      opened_at: '2026-10-20T10:00',
      closed_at: '2026-10-20T14:00',
      notes: 'n',
      analysis_id: '8',
    });
    expect(valuesFromEntry(makeEntry())).toMatchObject({
      exit: '',
      closed_at: '',
      analysis_id: '',
    });
  });
});

describe('parseJournalId', () => {
  it.each([
    ['1', 1],
    ['42', 42],
    ['0', null],
    ['-3', null],
    ['1.5', null],
    ['abc', null],
    ['9'.repeat(30), null],
  ])('parses %s', (raw, expected) => {
    expect(parseJournalId(raw)).toBe(expected);
  });

  it('rejects non-strings', () => {
    expect(parseJournalId(null)).toBeNull();
    expect(parseJournalId(undefined)).toBeNull();
  });
});

describe('rMultiple', () => {
  it('is null for an open trade', () => {
    expect(rMultiple(makeEntry())).toBeNull();
  });

  it('measures a long and a short in units of initial risk', () => {
    expect(rMultiple(makeClosedEntry({ entry: 1.1, stop: 1.09, exit: 1.12 }))).toBeCloseTo(2);
    expect(rMultiple(makeClosedEntry({ entry: 1.1, stop: 1.09, exit: 1.08 }))).toBeCloseTo(-2);
    expect(
      rMultiple(makeClosedEntry({ side: 'short', entry: 1.1, stop: 1.11, exit: 1.09 }))
    ).toBeCloseTo(1);
  });

  it('is null when the risk is zero or the result is not finite', () => {
    expect(rMultiple(makeClosedEntry({ entry: 1.1, stop: 1.1 }))).toBeNull();
    expect(rMultiple(makeClosedEntry({ exit: Number.NaN }))).toBeNull();
  });

  it('formats with a sign and two decimals', () => {
    expect(formatR(2)).toBe('+2.00R');
    expect(formatR(-0.5)).toBe('-0.50R');
    expect(formatR(0)).toBe('0.00R');
    expect(formatR(null)).toBe('—');
  });
});

describe('params', () => {
  it('keeps only well-formed cursors', () => {
    expect(parseJournalCursor('abc_-=')).toBe('abc_-=');
    expect(parseJournalCursor('a b')).toBeUndefined();
    expect(parseJournalCursor('x'.repeat(97))).toBeUndefined();
    expect(parseJournalCursor(['abc'])).toBe('abc');
    expect(parseJournalCursor(undefined)).toBeUndefined();
    expect(parseJournalCursor('')).toBeUndefined();
  });

  it('builds the list href', () => {
    expect(JOURNAL_PAGE_SIZE).toBe(25);
    expect(journalHref()).toBe('/journal');
    expect(journalHref('abc')).toBe('/journal?cursor=abc');
  });
});

describe('prefill', () => {
  it('links to /journal/new with the setup from a BUY analysis', () => {
    const href = buildLogTradeHref(
      makeAnalysis({
        id: 9,
        symbol: 'EURUSD',
        tf: '1h',
        verdict: { action: 'BUY', confidence: 70, entry: 1.0975, stop: 1.0955 },
      })
    );
    const url = new URL(href, 'http://x');
    expect(url.pathname).toBe('/journal/new');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      symbol: 'EURUSD',
      timeframe: '1h',
      side: 'long',
      entry: '1.0975',
      stop: '1.0955',
      analysis_id: '9',
    });
  });

  it('maps SELL to short and leaves out what a HOLD or failed analysis lacks', () => {
    const sell = buildLogTradeHref(
      makeAnalysis({ verdict: { action: 'SELL', confidence: 70, entry: 2, stop: 2.5 } })
    );
    expect(new URL(sell, 'http://x').searchParams.get('side')).toBe('short');
    const hold = new URL(
      buildLogTradeHref(makeAnalysis({ verdict: { action: 'HOLD', confidence: 10 } })),
      'http://x'
    );
    expect(hold.searchParams.has('side')).toBe(false);
    expect(hold.searchParams.has('entry')).toBe(false);
    const none = new URL(buildLogTradeHref(makeAnalysis({ verdict: null })), 'http://x');
    expect(none.searchParams.get('symbol')).toBe('EURUSD');
  });

  it('writes small prices as plain decimals', () => {
    const url = new URL(
      buildLogTradeHref(
        makeAnalysis({ verdict: { action: 'BUY', confidence: 1, entry: 1e-7, stop: 5e-8 } })
      ),
      'http://x'
    );
    expect(url.searchParams.get('entry')).toBe('0.0000001');
  });

  it('parses only valid prefill values from untrusted query params', () => {
    expect(
      parsePrefill({
        symbol: 'GBPUSD',
        timeframe: '4h',
        side: 'short',
        entry: '1.25',
        stop: '1.26',
        analysis_id: '7',
      })
    ).toEqual({
      symbol: 'GBPUSD',
      timeframe: '4h',
      side: 'short',
      entry: '1.25',
      stop: '1.26',
      analysis_id: '7',
    });
    expect(
      parsePrefill({
        symbol: '<script>',
        timeframe: '9h',
        side: 'up',
        entry: 'abc',
        stop: ['1.2e3'],
        analysis_id: '-1',
        extra: 'x',
      })
    ).toEqual({});
    expect(parsePrefill({ symbol: ['EURUSD', 'x'] })).toEqual({ symbol: 'EURUSD' });
  });
});
