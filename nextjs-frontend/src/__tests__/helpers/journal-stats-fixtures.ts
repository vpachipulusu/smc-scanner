import type { JournalStats } from '@/lib/journal/stats';

export function makeStats(overrides: Partial<JournalStats['summary']> = {}): JournalStats {
  return {
    summary: {
      closed_trades: 4,
      open_trades: 2,
      wins: 2,
      losses: 1,
      breakeven: 1,
      win_rate: 0.5,
      average_r: 0.75,
      avg_win_r: 2,
      avg_loss_r: -1,
      expectancy: 0.75,
      total_r: 3,
      ...overrides,
    },
    cumulative: [
      { entry_id: 1, closed_at: '2026-10-18T10:00:00Z', r: 2, cumulative_r: 2 },
      { entry_id: 2, closed_at: '2026-10-19T10:00:00Z', r: -1, cumulative_r: 1 },
      { entry_id: 3, closed_at: '2026-10-20T10:00:00Z', r: 2, cumulative_r: 3 },
    ],
  };
}

export function makeEmptyStats(): JournalStats {
  return {
    ...makeStats({
      closed_trades: 0,
      open_trades: 3,
      wins: 0,
      losses: 0,
      breakeven: 0,
      win_rate: null,
      average_r: null,
      avg_win_r: null,
      avg_loss_r: null,
      expectancy: null,
      total_r: 0,
    }),
    cumulative: [],
  };
}
