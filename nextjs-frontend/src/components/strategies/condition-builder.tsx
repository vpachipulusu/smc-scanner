'use client';

import { useState } from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { countModes, lowerMinScore, minScoreProblem } from '@/lib/strategies/builder';
import type { ConditionInfo } from '@/lib/strategies/catalogue';
import {
  CONDITION_MODES,
  condField,
  paramField,
  type ConditionMode,
  type ConditionValue,
  type FieldErrors,
} from '@/lib/strategies/form';
import { STRATEGY_LIMITS } from '@/lib/strategies/schema';
import { ParamInput } from './param-input';

/**
 * Every catalogue condition as a radio group (Off / Required / Scored) with its params rendered
 * from its schema, plus `min_score`, which is bounded by the number of scored conditions: turning
 * a scored condition off lowers it with the bound. Plain radios and inputs, so the keyboard works.
 */

const MODE_LABELS: Readonly<Record<ConditionMode, string>> = {
  off: 'Off',
  require: 'Required',
  score: 'Scored',
};

type ConditionBuilderProps = {
  catalogue: readonly ConditionInfo[];
  conditions: Readonly<Record<string, ConditionValue>>;
  minScore: string;
  errors: FieldErrors;
};

export function ConditionBuilder({
  catalogue,
  conditions,
  minScore,
  errors,
}: ConditionBuilderProps) {
  const [modes, setModes] = useState<Readonly<Record<string, ConditionMode>>>(() =>
    Object.fromEntries(catalogue.map((info) => [info.key, conditions[info.key]?.mode ?? 'off']))
  );
  const [minScoreText, setMinScoreText] = useState(minScore);
  const [notice, setNotice] = useState('');
  const counts = countModes(modes);
  // The server's message stands until the value is changed; then the live check takes over.
  const minScoreError =
    minScoreProblem(minScoreText, counts.score) ??
    (minScoreText === minScore ? errors.min_score : undefined);

  const changeMode = (key: string, mode: ConditionMode) => {
    const next = { ...modes, [key]: mode };
    const scored = countModes(next).score;
    setModes(next);
    const lowered = lowerMinScore(minScoreText, scored);
    if (lowered !== null) setMinScoreText(String(lowered));
    setNotice(lowered === null ? '' : `Min score lowered to ${lowered}.`);
  };

  const listError = errors.conditions;

  return (
    <fieldset className="space-y-4" aria-describedby="strategy-conditions-hint">
      <legend className="text-base font-semibold">Conditions</legend>
      <p id="strategy-conditions-hint" className="text-sm text-muted-foreground">
        Required conditions must all pass. Each scored condition that passes adds a point, and a
        zone needs at least the min score. Up to {STRATEGY_LIMITS.conditionsMax} of each.
      </p>
      <p role="status" className="text-sm" data-testid="condition-counts">
        {counts.require} required, {counts.score} scored{notice && `. ${notice}`}
      </p>
      {listError && (
        <p
          role="alert"
          tabIndex={-1}
          data-form-alert
          className="text-sm text-crit-foreground outline-none"
        >
          {listError}
        </p>
      )}

      <ul className="divide-y rounded-lg border">
        {catalogue.map((info) => {
          const mode = modes[info.key] ?? 'off';
          const modeError = errors[condField(info.key)];
          const errorId = `strategy-cond-${info.key}-error`;
          return (
            <li key={info.key} className="p-3">
              <fieldset
                aria-describedby={modeError ? errorId : undefined}
                className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between"
              >
                <legend className="float-left text-sm font-medium md:max-w-[50%]">
                  {info.label}
                  <span className="block font-mono text-xs font-normal text-muted-foreground">
                    {info.key}
                  </span>
                </legend>
                <div className="clear-left flex flex-wrap gap-x-4 md:clear-none">
                  {CONDITION_MODES.map((option) => (
                    <label key={option} className="flex min-h-11 items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name={condField(info.key)}
                        value={option}
                        checked={mode === option}
                        onChange={() => changeMode(info.key, option)}
                        className="size-4"
                      />
                      {MODE_LABELS[option]}
                    </label>
                  ))}
                </div>
              </fieldset>
              {modeError && (
                <p
                  id={errorId}
                  tabIndex={-1}
                  data-form-alert
                  className="mt-1 text-xs text-crit-foreground outline-none"
                >
                  {modeError}
                </p>
              )}
              {info.params.length > 0 && (
                <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {info.params.map((field) => {
                    const name = paramField(info.key, field.name);
                    return (
                      <ParamInput
                        key={field.name}
                        field={field}
                        id={`strategy-param-${info.key}-${field.name}`}
                        name={name}
                        defaultValue={conditions[info.key]?.params[field.name] ?? ''}
                        disabled={mode === 'off'}
                        error={errors[name]}
                      />
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <div className="max-w-xs">
        <Label htmlFor="strategy-min_score" className="mb-1 block">
          Min score
        </Label>
        <Input
          id="strategy-min_score"
          name="min_score"
          type="number"
          inputMode="numeric"
          min={0}
          max={counts.score}
          step={1}
          value={minScoreText}
          onChange={(event) => setMinScoreText(event.target.value)}
          aria-invalid={minScoreError ? true : undefined}
          aria-describedby={
            minScoreError
              ? 'strategy-min_score-hint strategy-min_score-error'
              : 'strategy-min_score-hint'
          }
        />
        <p id="strategy-min_score-hint" className="mt-1 text-xs text-muted-foreground">
          {counts.score === 0
            ? 'Score at least one condition to require a min score.'
            : `0 to ${counts.score}, the number of scored conditions.`}
        </p>
        {minScoreError && (
          <p
            id="strategy-min_score-error"
            aria-live="polite"
            className="mt-1 text-xs text-crit-foreground"
          >
            {minScoreError}
          </p>
        )}
      </div>
    </fieldset>
  );
}
