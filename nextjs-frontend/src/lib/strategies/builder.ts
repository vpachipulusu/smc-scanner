import type { ConditionMode } from './form';

/**
 * Pure helpers behind the condition builder: how many conditions each mode holds and the
 * `min_score` bound, which can never exceed the number of scored conditions.
 */

export type ModeCounts = Readonly<Record<ConditionMode, number>>;

export function countModes(byKey: Readonly<Record<string, ConditionMode>>): ModeCounts {
  const modes = Object.values(byKey);
  return {
    off: modes.filter((mode) => mode === 'off').length,
    require: modes.filter((mode) => mode === 'require').length,
    score: modes.filter((mode) => mode === 'score').length,
  };
}

const WHOLE_NUMBER = /^\d{1,3}$/;

/**
 * The new `min_score` when fewer conditions are scored: `scored` if `raw` is a whole number above
 * it, else null (leave it alone; text that is not a whole number is flagged, never rewritten).
 */
export function lowerMinScore(raw: string, scored: number): number | null {
  const text = raw.trim();
  if (!WHOLE_NUMBER.test(text)) return null;
  const bound = Math.max(scored, 0);
  return Number(text) > bound ? bound : null;
}

/** The message for a `min_score` the API would reject, or null when it is within 0..scored. */
export function minScoreProblem(raw: string, scored: number): string | null {
  const text = raw.trim();
  if (text === '') return null;
  if (!WHOLE_NUMBER.test(text) || Number(text) > scored) {
    return `Enter a whole number from 0 to ${scored} (the scored conditions).`;
  }
  return null;
}
