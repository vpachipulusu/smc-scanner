/**
 * Strategy condition results on scan rows (`row.conditions`: condition key -> passed). Keys come
 * from the backend, so only condition-key shaped names with boolean values are kept, and labels
 * come from `GET /config` `conditions`, with a readable fallback for a key the catalogue lacks.
 */

/** The backend's condition keys: lower-case words joined by underscores. */
export const CONDITION_KEY_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;
const MAX_CONDITIONS = 32;

export type ConditionChip = { key: string; label: string; met: boolean };

/** Condition key -> label, built from the `/config` catalogue. */
export type ConditionLabels = Readonly<Record<string, string>>;

/** A fresh record with only well-formed entries, in the API's order. */
export function checkedConditions(value: Record<string, unknown>): Record<string, boolean> {
  const entries = Object.entries(value)
    .filter(([key, met]) => CONDITION_KEY_PATTERN.test(key) && typeof met === 'boolean')
    .slice(0, MAX_CONDITIONS);
  return Object.fromEntries(entries) as Record<string, boolean>;
}

const MAX_LABEL = 64;

function isCatalogueItem(item: unknown): item is { key: string; label: string } {
  if (typeof item !== 'object' || item === null) return false;
  const { key, label } = item as Record<string, unknown>;
  return typeof key === 'string' && CONDITION_KEY_PATTERN.test(key) && typeof label === 'string';
}

/** `/config` is only shape-checked for its choice lists, so the catalogue is checked here. */
export function conditionLabels(catalogue: unknown): ConditionLabels {
  if (!Array.isArray(catalogue)) return {};
  const entries = catalogue
    .filter(isCatalogueItem)
    .map((item) => [item.key, item.label.slice(0, MAX_LABEL)] as const);
  return Object.fromEntries(entries);
}

/** `max_zone_age` -> `Max zone age`, for keys the catalogue does not name. */
export function fallbackLabel(key: string): string {
  const words = key.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** One chip per valid condition on the row; empty when the row carries none. */
export function conditionChips(
  conditions: Readonly<Record<string, unknown>> | undefined,
  labels: ConditionLabels = {}
): ConditionChip[] {
  if (!conditions || typeof conditions !== 'object') return [];
  return Object.entries(checkedConditions(conditions)).map(([key, met]) => ({
    key,
    label: Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : fallbackLabel(key),
    met,
  }));
}
