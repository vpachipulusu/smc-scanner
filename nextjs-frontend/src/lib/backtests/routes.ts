/** The backtest page of a strategy, optionally showing one run. */
export function backtestHref(slug: string, id?: number): string {
  const path = `/strategies/${encodeURIComponent(slug)}/backtest`;
  return id === undefined ? path : `${path}?run=${id}`;
}

/** A `?run=` value as a run id, or null. */
export function parseRunId(raw: string | string[] | undefined): number | null {
  if (typeof raw !== 'string' || !/^\d{1,15}$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
