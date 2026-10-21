import type { JournalEntryOut } from '@/lib/api/journal';

export function makeEntry(overrides: Partial<JournalEntryOut> = {}): JournalEntryOut {
  return {
    id: 1,
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
    created_at: '2026-10-20T10:01:00Z',
    updated_at: '2026-10-20T10:01:00Z',
    ...overrides,
  };
}

export function makeClosedEntry(overrides: Partial<JournalEntryOut> = {}): JournalEntryOut {
  return makeEntry({ exit: 1.12, closed_at: '2026-10-20T14:00:00Z', ...overrides });
}
