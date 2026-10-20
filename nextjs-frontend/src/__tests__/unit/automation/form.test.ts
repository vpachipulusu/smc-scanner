/** The schedule form parser mirrors the API limits and reports each bad field on its own. */
import { describe, expect, it } from 'vitest';
import {
  EMPTY_VALUES,
  parseScheduleForm,
  parseScheduleId,
  parseSymbols,
  valuesFromSchedule,
} from '@/lib/automation/form';
import { makeSchedule } from '../../helpers/automation-fixtures';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const VALID = {
  name: 'Morning scan',
  source: 'demo',
  tf: '15m',
  symbols: 'EURUSD, XAUUSD',
  frequency: '1h',
};

describe('parseScheduleForm', () => {
  it('builds the API body, applying defaults for empty numbers and the chat id', () => {
    const parsed = parseScheduleForm(form({ ...VALID, only_on_change: 'on', enabled: 'on' }));

    expect(parsed).toEqual({
      ok: true,
      body: {
        name: 'Morning scan',
        source: 'demo',
        tf: '15m',
        symbols: ['EURUSD', 'XAUUSD'],
        frequency: '1h',
        min_score: 2,
        min_confidence: 0,
        only_on_change: true,
        send_hold: false,
        enabled: true,
        telegram_chat_id: null,
      },
    });
  });

  it('accepts numeric and @channel chat ids and explicit limits', () => {
    for (const chat of ['-1001234567890', '@my_channel']) {
      const parsed = parseScheduleForm(
        form({ ...VALID, telegram_chat_id: chat, min_score: '4', min_confidence: '72.5' })
      );
      expect(parsed).toMatchObject({
        ok: true,
        body: { telegram_chat_id: chat, min_score: 4, min_confidence: 72.5 },
      });
    }
  });

  it('ignores fields that are not on the allow-list', () => {
    const parsed = parseScheduleForm(form({ ...VALID, is_admin: 'true', id: '9' }));
    expect(parsed.ok && Object.keys(parsed.body)).not.toContain('is_admin');
    expect(parsed.ok && Object.keys(parsed.body)).not.toContain('id');
  });

  it('reports every invalid field with its own message and keeps the values', () => {
    const parsed = parseScheduleForm(
      form({
        name: '   ',
        source: 'evil',
        tf: '2h',
        symbols: 'EUR/USD',
        frequency: '5m',
        min_score: '5',
        min_confidence: '101',
        telegram_chat_id: 'not a chat',
        only_on_change: 'on',
      })
    );

    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(Object.keys(parsed.errors).sort()).toEqual([
      'frequency',
      'min_confidence',
      'min_score',
      'name',
      'source',
      'symbols',
      'telegram_chat_id',
      'tf',
    ]);
    expect(parsed.values.symbols).toBe('EUR/USD');
    expect(parsed.values.only_on_change).toBe(true);
  });

  it.each([
    ['a name over 64 characters', { name: 'x'.repeat(65) }, 'name'],
    ['no symbols', { symbols: ' , ;' }, 'symbols'],
    [
      'more than 50 symbols',
      { symbols: Array.from({ length: 51 }, (_, i) => `S${i}`).join(',') },
      'symbols',
    ],
    ['a symbol over 32 characters', { symbols: 'A'.repeat(33) }, 'symbols'],
    ['a fractional score', { min_score: '1.5' }, 'min_score'],
    ['a negative confidence', { min_confidence: '-1' }, 'min_confidence'],
    ['a non-numeric confidence', { min_confidence: '1e2' }, 'min_confidence'],
    ['a chat id with a short channel name', { telegram_chat_id: '@abc' }, 'telegram_chat_id'],
  ])('rejects %s', (_label, override, field) => {
    const parsed = parseScheduleForm(form({ ...VALID, ...override }));
    expect(parsed.ok).toBe(false);
    expect(!parsed.ok && parsed.errors[field as keyof typeof parsed.errors]).toBeTruthy();
  });

  it('treats missing and non-string fields as empty', () => {
    const data = new FormData();
    data.append('name', new File(['x'], 'x.txt'));
    const parsed = parseScheduleForm(data);
    expect(!parsed.ok && parsed.errors.name).toBe('Enter a name.');
  });
});

describe('helpers', () => {
  it('splits symbols on commas, spaces and semicolons and removes duplicates', () => {
    expect(parseSymbols('EURUSD, XAUUSD;EURUSD  BTCUSD')).toEqual(['EURUSD', 'XAUUSD', 'BTCUSD']);
  });

  it('turns a schedule into form values', () => {
    expect(
      valuesFromSchedule(makeSchedule({ symbols: ['A', 'B'], telegram_chat_id: null }))
    ).toMatchObject({ symbols: 'A, B', telegram_chat_id: '', min_score: '2' });
    expect(EMPTY_VALUES.enabled).toBe(true);
  });

  it.each([
    ['7', 7],
    ['0', null],
    ['-1', null],
    ['1.5', null],
    ['abc', null],
    ['12345678901234567890', null],
  ])('parses schedule id %s', (raw, expected) => {
    expect(parseScheduleId(raw)).toBe(expected);
  });

  it('rejects ids that are not strings', () => {
    expect(parseScheduleId(undefined)).toBeNull();
    expect(parseScheduleId(7)).toBeNull();
  });
});
