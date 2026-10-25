'use client';

import { useState } from 'react';

import { Label } from '@/components/ui/label';
import { findStrategy, type StrategyOption } from '@/lib/scan/strategy-options';

/**
 * The strategy select shared by the scan form and the schedule form. Built-in and custom
 * strategies are grouped; a slug that is not in the list (a deleted strategy, a hand-edited URL)
 * stays selectable and is flagged so the form never silently swaps it. Hints are linked with
 * `aria-describedby`.
 */

export const STRATEGY_LABEL = 'Strategy';
export const STRATEGY_MTF_HINT =
  'This strategy adds higher/lower timeframe context even when that option is off.';
export const STRATEGY_MISSING_HINT = 'This strategy no longer exists. Pick another one.';
export const STRATEGY_NOT_FOUND_SUFFIX = ' (not found)';

const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';
const HINT_CLASSES = 'mt-1 text-xs text-muted-foreground';
const WARN_HINT_CLASSES = 'mt-1 text-xs text-warn-foreground';

type StrategyPickerProps = {
  id: string;
  name: string;
  options: ReadonlyArray<StrategyOption>;
  defaultValue: string;
  /** Called with the picked strategy (undefined for a slug that is not in the list). */
  onSelect?: (option: StrategyOption | undefined) => void;
  /**
   * Whether `options` is the full list. /config lists only the built-ins when the store is down,
   * so a custom slug is flagged as missing only when the full list loaded.
   */
  complete?: boolean;
  /** A fixed hint shown first, e.g. what picking does in this form. */
  hint?: string;
  error?: string;
};

type Hint = { id: string; text: string; warn?: boolean };

function OptionList({ options }: { options: ReadonlyArray<StrategyOption> }) {
  const builtin = options.filter((option) => option.builtin);
  const custom = options.filter((option) => !option.builtin);
  const items = (list: StrategyOption[]) =>
    list.map((option) => (
      <option key={option.slug} value={option.slug}>
        {option.name}
      </option>
    ));
  return (
    <>
      {builtin.length > 0 && <optgroup label="Built-in">{items(builtin)}</optgroup>}
      {custom.length > 0 && <optgroup label="Custom">{items(custom)}</optgroup>}
    </>
  );
}

export function StrategyPicker({
  id,
  name,
  options,
  defaultValue,
  onSelect,
  complete = true,
  hint,
  error,
}: StrategyPickerProps) {
  const [value, setValue] = useState(defaultValue);
  const selected = findStrategy(options, value);
  // With no list, or only part of it (the API or store is down), an unknown slug is not an error.
  const missing = selected === undefined && complete && options.length > 0;
  const hints = [
    hint ? { id: `${id}-hint`, text: hint } : null,
    selected?.mtf ? { id: `${id}-mtf-hint`, text: STRATEGY_MTF_HINT } : null,
    missing ? { id: `${id}-missing`, text: STRATEGY_MISSING_HINT, warn: true } : null,
  ].filter((item): item is Hint => item !== null);
  const errorId = `${id}-error`;
  const describedBy = [...hints.map((item) => item.id), error ? errorId : null]
    .filter(Boolean)
    .join(' ');

  return (
    <div className="sm:col-span-2">
      <Label htmlFor={id} className="mb-1 block">
        {STRATEGY_LABEL}
      </Label>
      <select
        id={id}
        name={name}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          onSelect?.(findStrategy(options, event.target.value));
        }}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={SELECT_CLASSES}
      >
        {selected === undefined && (
          <option value={value}>{missing ? `${value}${STRATEGY_NOT_FOUND_SUFFIX}` : value}</option>
        )}
        <OptionList options={options} />
      </select>
      {hints.map((item) => (
        <p key={item.id} id={item.id} className={item.warn ? WARN_HINT_CLASSES : HINT_CLASSES}>
          {item.text}
        </p>
      ))}
      {error && (
        <p id={errorId} className="mt-1 text-xs text-crit-foreground">
          {error}
        </p>
      )}
    </div>
  );
}
