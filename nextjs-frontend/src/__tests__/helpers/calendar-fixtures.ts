import type { CalendarEventOut, CalendarResponse } from '@/lib/api/calendar';

export function makeEvent(overrides: Partial<CalendarEventOut> = {}): CalendarEventOut {
  return {
    currency: 'USD',
    impact: 'high',
    time: '2026-10-21T12:30:00Z',
    title: 'Non-Farm Payrolls',
    actual: null,
    forecast: 180,
    previous: 175.5,
    ...overrides,
  };
}

export function makeCalendar(overrides: Partial<CalendarResponse> = {}): CalendarResponse {
  return {
    symbol: 'EURUSD',
    currencies: ['EUR', 'USD'],
    calendar_status: 'fresh',
    immediate_risk: 'none',
    as_of: '2026-10-21T10:00:00Z',
    fetched_at: '2026-10-21T09:45:00Z',
    window_hours: 24,
    events: [makeEvent()],
    ...overrides,
  };
}
