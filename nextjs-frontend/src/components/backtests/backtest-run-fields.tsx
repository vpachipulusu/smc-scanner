'use client';

import { useState, type ReactNode } from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatCost } from '@/lib/backtests/format';
import {
  BACKTEST_LIMITS as L,
  BACKTEST_SOURCES,
  BACKTEST_TIMEFRAMES,
  SPLITS,
  backtestCost,
  splitSymbols,
  type BacktestFieldErrors,
  type BacktestFieldName,
  type BacktestFormValues,
} from '@/lib/backtests/form';

/**
 * The inputs of the "Run backtest" form. Bars, symbols and stride are controlled so the cost
 * (symbols x bars x bars / stride, capped by the API) updates as they change; the rest are plain
 * inputs. Each hint and error is linked with `aria-describedby`.
 */

const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const HINTS: Partial<Record<BacktestFieldName, string>> = {
  symbols: 'Optional. Commas or spaces between names; blank uses the source’s watchlist.',
  split: 'Time: train on the early bars, test on the later ones. Symbols: test on other symbols.',
  train_fraction: `The share used for training, ${L.minTrainFraction} to ${L.maxTrainFraction}.`,
  seed: 'Keep it fixed. Re-running with new seeds until one passes is data snooping.',
  stride: 'Above 1 replays every n-th bar only: faster, but approximate.',
  spread: 'In price units, paid once per trade.',
};

type FieldProps = {
  name: BacktestFieldName;
  label: string;
  errors: BacktestFieldErrors;
  children: (props: {
    id: string;
    name: BacktestFieldName;
    'aria-invalid'?: true;
    'aria-describedby'?: string;
  }) => ReactNode;
};

function Field({ name, label, errors, children }: FieldProps) {
  const id = `backtest-${name}`;
  const hint = HINTS[name];
  const error = errors[name];
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(' ');
  return (
    <div>
      <Label htmlFor={id} className="mb-1 block">
        {label}
      </Label>
      {children({
        id,
        name,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy || undefined,
      })}
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-crit-foreground">
          {error}
        </p>
      )}
    </div>
  );
}

/** The cost line under the size fields; over the cap it says so in words, not only colour. */
export function costText(
  symbols: string,
  bars: string,
  stride: string
): {
  text: string;
  over: boolean;
} {
  const count = splitSymbols(symbols).length;
  const barCount = Number(bars);
  const strideCount = Number(stride);
  const cap = formatCost(L.maxCost);
  if (count === 0 || !(barCount > 0) || !(strideCount > 0)) {
    return {
      text: `Cost cap: symbols × bars × bars ÷ stride must be at most ${cap} (with the watchlist, its size counts as the symbols). A run at the cap takes about 15 minutes.`,
      over: false,
    };
  }
  const cost = backtestCost(count, barCount, strideCount);
  const over = cost > L.maxCost;
  return {
    text: `Cost: ${count} × ${barCount} × ${barCount} ÷ ${strideCount} = ${formatCost(cost)} of at most ${cap}.${over ? ' Too large: use fewer symbols or bars, or a larger stride.' : ''}`,
    over,
  };
}

type RunFieldsProps = { values: BacktestFormValues; errors: BacktestFieldErrors };

export function BacktestRunFields({ values, errors }: RunFieldsProps) {
  const [bars, setBars] = useState(values.bars);
  const [symbols, setSymbols] = useState(values.symbols);
  const [stride, setStride] = useState(values.stride);
  const cost = costText(symbols, bars, stride);
  const number = (
    name: BacktestFieldName,
    label: string,
    step: string,
    min: number,
    max: number
  ) => (
    <Field name={name} label={label} errors={errors}>
      {(props) => (
        <Input
          {...props}
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          max={max}
          defaultValue={values[name]}
        />
      )}
    </Field>
  );

  return (
    <div className="space-y-6">
      <fieldset className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <legend className="mb-2 text-sm font-semibold">Data</legend>
        <Field name="source" label="Source" errors={errors}>
          {(props) => (
            <select {...props} defaultValue={values.source} className={SELECT_CLASSES}>
              {BACKTEST_SOURCES.map((source) => (
                <option key={source} value={source}>
                  {source === 'mt5' ? 'MT5' : 'Demo'}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field name="tf" label="Timeframe" errors={errors}>
          {(props) => (
            <select {...props} defaultValue={values.tf} className={SELECT_CLASSES}>
              {BACKTEST_TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field name="bars" label="Bars" errors={errors}>
          {(props) => (
            <Input
              {...props}
              type="number"
              inputMode="numeric"
              step={1}
              min={L.minBars}
              max={L.maxBars}
              value={bars}
              onChange={(event) => setBars(event.target.value)}
            />
          )}
        </Field>
        <Field name="stride" label="Stride" errors={errors}>
          {(props) => (
            <Input
              {...props}
              type="number"
              inputMode="numeric"
              step={1}
              min={L.minStride}
              max={L.maxStride}
              value={stride}
              onChange={(event) => setStride(event.target.value)}
            />
          )}
        </Field>
        <div className="sm:col-span-2 lg:col-span-4">
          <Field name="symbols" label="Symbols" errors={errors}>
            {(props) => (
              <Input
                {...props}
                value={symbols}
                onChange={(event) => setSymbols(event.target.value)}
                placeholder="EURUSD, XAUUSD"
                autoComplete="off"
                spellCheck={false}
              />
            )}
          </Field>
          <p
            className={`mt-2 text-xs ${cost.over ? 'text-crit-foreground' : 'text-muted-foreground'}`}
            data-testid="backtest-cost"
          >
            {cost.text}
          </p>
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <legend className="mb-2 text-sm font-semibold">Exit rules</legend>
        {number('rr', 'Reward to risk', 'any', 0, L.maxRr)}
        {number('stop_buffer_atr', 'Stop buffer (ATR)', 'any', 0, L.maxStopBufferAtr)}
        {number('time_stop_bars', 'Time stop (bars)', '1', L.minTimeStopBars, L.maxTimeStopBars)}
        {number('spread', 'Spread', 'any', 0, L.maxSpread)}
        {number('min_risk_atr', 'Min risk (ATR)', 'any', 0, L.maxMinRiskAtr)}
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-3">
        <legend className="mb-2 text-sm font-semibold">Walk-forward split</legend>
        <Field name="split" label="Split" errors={errors}>
          {(props) => (
            <select {...props} defaultValue={values.split} className={SELECT_CLASSES}>
              {SPLITS.map((split) => (
                <option key={split} value={split}>
                  {split === 'time' ? 'By time' : 'By symbol'}
                </option>
              ))}
            </select>
          )}
        </Field>
        {number('train_fraction', 'Train fraction', 'any', L.minTrainFraction, L.maxTrainFraction)}
        {number('seed', 'Seed', '1', 0, L.maxSeed)}
      </fieldset>
    </div>
  );
}
