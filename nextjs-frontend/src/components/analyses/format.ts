/** Display helpers for the analysis detail page. Missing or non-finite values read "N/A", never NaN. */

export const NOT_AVAILABLE = 'N/A';

const ID_PATTERN = /^[1-9]\d*$/;
const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i;

/** Ids are database integers; anything above int32 cannot exist, so it is a 404 and never fetched. */
const MAX_ID = 2_147_483_647;

/** The route's `[id]` as a positive int32, or null for anything else. */
export function parseAnalysisId(raw: string): number | null {
  if (!ID_PATTERN.test(raw)) return null;
  const id = Number(raw);
  return id <= MAX_ID ? id : null;
}

/** The strings of a value that should be a list of strings; anything else is dropped. */
export function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
    : [];
}

/** The finite numbers of a value that should be a list of numbers. */
export function numberList(value: unknown): number[] {
  return Array.isArray(value) ? value.filter(isFiniteNumber) : [];
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** A price with decimals scaled to its size: 2 above 1000, 3 above 10, up to 5 above 1, else 6. */
export function formatPrice(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return NOT_AVAILABLE;
  const size = Math.abs(value);
  if (size >= 1000) return value.toFixed(2);
  if (size >= 10) return value.toFixed(3);
  const text = value.toFixed(size >= 1 ? 5 : 6);
  return text.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
}

/** "YYYY-MM-DD HH:mm UTC". A time without a zone is read as UTC; unparseable text is shown as is. */
export function formatUtc(value: string | null | undefined): string {
  if (!value) return NOT_AVAILABLE;
  const iso = value.includes('T') ? value : value.replace(' ', 'T');
  const date = new Date(HAS_ZONE.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/** Text or "N/A" when empty. */
export function textOrNA(value: string | null | undefined): string {
  return value && value.trim() ? value : NOT_AVAILABLE;
}
