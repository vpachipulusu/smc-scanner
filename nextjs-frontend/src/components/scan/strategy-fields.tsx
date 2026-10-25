'use client';

import { useState } from 'react';

import { StrategyPicker } from '@/components/scan/strategy-picker';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { LIMITS } from '@/lib/scan/params';
import type { StrategyVerdicts } from '@/lib/backtests/verdict';
import type { StrategyOption } from '@/lib/scan/strategy-options';

/**
 * The scan form's strategy select with the two tuning fields it prefills. Picking a strategy copies
 * its swing length and near distance into the fields; the user can still change them, and the
 * submitted values always win over the strategy's (as in the API). Rendered inside the form's grid.
 */

export const STRATEGY_PREFILL_HINT = 'Picking a strategy fills in its swing length and near.';

type StrategyFieldsProps = {
  options: ReadonlyArray<StrategyOption>;
  /** Whether `options` is the full list (see `StrategyPicker`). */
  complete?: boolean;
  strategy: string;
  swing: number;
  near: number;
  /** Latest backtest verdict by slug, shown in the picker. */
  verdicts?: StrategyVerdicts;
};

export function StrategyFields({
  options,
  complete,
  strategy,
  swing,
  near,
  verdicts,
}: StrategyFieldsProps) {
  const [swingValue, setSwingValue] = useState(String(swing));
  const [nearValue, setNearValue] = useState(String(near));

  return (
    <>
      <StrategyPicker
        id="scan-strategy"
        name="strategy"
        options={options}
        complete={complete}
        verdicts={verdicts}
        defaultValue={strategy}
        hint={STRATEGY_PREFILL_HINT}
        onSelect={(option) => {
          if (!option) return;
          setSwingValue(String(option.swingLength));
          setNearValue(String(option.nearAtr));
        }}
      />
      <div>
        <Label htmlFor="scan-swing" className="mb-1 block">
          Swing length
        </Label>
        <Input
          id="scan-swing"
          name="swing"
          type="number"
          inputMode="numeric"
          min={1}
          max={LIMITS.maxSwing}
          step={1}
          value={swingValue}
          onChange={(event) => setSwingValue(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="scan-near" className="mb-1 block">
          Near (ATR)
        </Label>
        <Input
          id="scan-near"
          name="near"
          type="number"
          inputMode="decimal"
          min={0}
          max={LIMITS.maxNear}
          // Any value: a strategy's near (e.g. 0.25) must not trip native step validation.
          step="any"
          value={nearValue}
          onChange={(event) => setNearValue(event.target.value)}
        />
      </div>
    </>
  );
}
