import type { JobLogOut, RunOut, ScheduleOut } from '@/lib/api/schedules';

export function makeSchedule(overrides: Partial<ScheduleOut> = {}): ScheduleOut {
  return {
    id: 1,
    name: 'Morning scan',
    source: 'demo',
    tf: '1h',
    symbols: ['EURUSD'],
    frequency: '1h',
    min_score: 2,
    min_confidence: 0,
    only_on_change: false,
    send_hold: false,
    enabled: true,
    telegram_chat_id: null,
    last_run_at: '2026-10-20T14:03:00Z',
    next_run_at: '2026-10-20T15:03:00Z',
    ...overrides,
  };
}

export function makeLog(overrides: Partial<JobLogOut> = {}): JobLogOut {
  return {
    id: 10,
    schedule_id: 1,
    started_at: '2026-10-20T14:03:00Z',
    finished_at: '2026-10-20T14:03:02Z',
    duration_ms: 2300,
    status: 'success',
    hits: 3,
    delivered: 2,
    skipped: 1,
    skip_reason: null,
    error: null,
    ...overrides,
  };
}

export function makeRun(overrides: Partial<RunOut> = {}): RunOut {
  return { status: 'ok', rows: 3, delivered: 2, skipped: 1, error_count: 0, ...overrides };
}
