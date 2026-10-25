'use client';

import Link from 'next/link';
import { useActionState, useEffect, useRef } from 'react';

import { saveScheduleAction } from '@/app/automation/actions';
import { MtfOptions } from '@/components/scan/mtf-options';
import { StrategyPicker } from '@/components/scan/strategy-picker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ScheduleOut } from '@/lib/api/schedules';
import {
  EMPTY_VALUES,
  FREQUENCIES,
  LIMITS,
  SOURCES,
  TIMEFRAMES,
  valuesFromSchedule,
  type FieldName,
  type FormValues,
} from '@/lib/automation/form';
import { IDLE_FORM_STATE } from '@/lib/automation/state';
import type { StrategyVerdicts } from '@/lib/backtests/verdict';
import type { StrategyOption } from '@/lib/scan/strategy-options';

/**
 * Create or edit a schedule. Plain labelled controls in a form, so it works with the keyboard
 * alone; each invalid field gets its own message, linked with `aria-describedby`.
 */

const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const CHECKBOX_LABEL_CLASSES = 'flex min-h-11 items-center gap-2 text-sm';

/** Scheduled runs scan with the strategy's swing length and near distance, fresh touches only. */
export const SCHEDULE_STRATEGY_HINT =
  "Picks and scores the hits. Runs use the strategy's swing length and near distance (fresh touches only).";

export function ScheduleForm({
  schedule,
  strategies = [],
  strategiesComplete = true,
  strategyVerdicts,
}: {
  schedule?: ScheduleOut;
  /** Picker choices (see `strategyOptions`); empty keeps the current strategy as the only one. */
  strategies?: ReadonlyArray<StrategyOption>;
  /** False when only /config's built-ins loaded, so unknown slugs are not flagged as deleted. */
  strategiesComplete?: boolean;
  /** Latest backtest verdict by slug, shown in the picker. */
  strategyVerdicts?: StrategyVerdicts;
}) {
  const [state, formAction, pending] = useActionState(saveScheduleAction, IDLE_FORM_STATE);
  const initial: FormValues = schedule ? valuesFromSchedule(schedule) : EMPTY_VALUES;
  const values = state.status === 'error' ? state.values : initial;
  const errors = state.status === 'error' ? state.errors : {};
  const editing = schedule !== undefined;
  const formRef = useRef<HTMLFormElement>(null);

  // Editing: land on the form. After a failed submit: land on the first invalid field.
  useEffect(() => {
    if (state.status === 'error') {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }
  }, [state]);
  useEffect(() => {
    if (editing) formRef.current?.querySelector<HTMLElement>('#schedule-name')?.focus();
  }, [editing]);

  const HINTED: readonly FieldName[] = ['symbols', 'min_confidence', 'telegram_chat_id'];
  const describedBy = (name: FieldName) =>
    [
      HINTED.includes(name) ? `schedule-${name}-hint` : null,
      errors[name] ? `schedule-${name}-error` : null,
    ]
      .filter(Boolean)
      .join(' ') || undefined;
  const fieldProps = (name: FieldName) => ({
    id: `schedule-${name}`,
    name,
    'aria-invalid': errors[name] ? true : undefined,
    'aria-describedby': describedBy(name),
  });
  const fieldError = (name: FieldName) =>
    errors[name] ? (
      <p id={`schedule-${name}-error`} className="mt-1 text-xs text-crit-foreground">
        {errors[name]}
      </p>
    ) : null;

  return (
    <form
      ref={formRef}
      action={formAction}
      aria-label={editing ? 'Edit schedule' : 'New schedule'}
      className="space-y-4"
      noValidate
    >
      {editing && <input type="hidden" name="id" value={schedule.id} />}
      {state.status === 'error' && state.message && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 p-3 text-sm text-crit-foreground"
        >
          {state.message}
        </p>
      )}
      {state.status === 'success' && (
        <p role="status" className="rounded-lg border p-3 text-sm">
          {state.message}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="sm:col-span-2">
          <Label htmlFor="schedule-name" className="mb-1 block">
            Name
          </Label>
          <Input
            {...fieldProps('name')}
            defaultValue={values.name}
            maxLength={LIMITS.nameMax}
            autoComplete="off"
            required
          />
          {fieldError('name')}
        </div>
        <div>
          <Label htmlFor="schedule-source" className="mb-1 block">
            Source
          </Label>
          <select {...fieldProps('source')} defaultValue={values.source} className={SELECT_CLASSES}>
            {SOURCES.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
          {fieldError('source')}
        </div>
        <div>
          <Label htmlFor="schedule-tf" className="mb-1 block">
            Timeframe
          </Label>
          <select {...fieldProps('tf')} defaultValue={values.tf} className={SELECT_CLASSES}>
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
          {fieldError('tf')}
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="schedule-symbols" className="mb-1 block">
            Symbols
          </Label>
          <Input
            {...fieldProps('symbols')}
            defaultValue={values.symbols}
            placeholder="EURUSD, XAUUSD"
            autoComplete="off"
            spellCheck={false}
            required
          />
          <p id="schedule-symbols-hint" className="mt-1 text-xs text-muted-foreground">
            Separate with commas or spaces, up to {LIMITS.symbolsMax}.
          </p>
          {fieldError('symbols')}
        </div>
        <div>
          <Label htmlFor="schedule-frequency" className="mb-1 block">
            Frequency
          </Label>
          <select
            {...fieldProps('frequency')}
            defaultValue={values.frequency}
            className={SELECT_CLASSES}
          >
            {FREQUENCIES.map((frequency) => (
              <option key={frequency} value={frequency}>
                every {frequency}
              </option>
            ))}
          </select>
          {fieldError('frequency')}
        </div>
        <div>
          <Label htmlFor="schedule-min_score" className="mb-1 block">
            Min score
          </Label>
          <Input
            {...fieldProps('min_score')}
            type="number"
            inputMode="numeric"
            min={0}
            max={LIMITS.minScoreMax}
            step={1}
            defaultValue={values.min_score}
          />
          {fieldError('min_score')}
        </div>
        <div>
          <Label htmlFor="schedule-min_confidence" className="mb-1 block">
            Min confidence
          </Label>
          <Input
            {...fieldProps('min_confidence')}
            type="number"
            inputMode="decimal"
            min={0}
            max={LIMITS.minConfidenceMax}
            step="any"
            defaultValue={values.min_confidence}
          />
          <p id="schedule-min_confidence-hint" className="mt-1 text-xs text-muted-foreground">
            0 to {LIMITS.minConfidenceMax}.
          </p>
          {fieldError('min_confidence')}
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="schedule-telegram_chat_id" className="mb-1 block">
            Telegram chat id
          </Label>
          <Input
            {...fieldProps('telegram_chat_id')}
            defaultValue={values.telegram_chat_id}
            placeholder="blank uses the default chat"
            autoComplete="off"
            spellCheck={false}
          />
          <p id="schedule-telegram_chat_id-hint" className="mt-1 text-xs text-muted-foreground">
            A numeric chat id or @channelname; blank uses the default chat.
          </p>
          {fieldError('telegram_chat_id')}
        </div>
        <StrategyPicker
          key={state.status === 'error' ? JSON.stringify(state.values) : state.status}
          id="schedule-strategy"
          name="strategy"
          options={strategies}
          complete={strategiesComplete}
          defaultValue={values.strategy}
          hint={SCHEDULE_STRATEGY_HINT}
          error={errors.strategy}
          verdicts={strategyVerdicts}
        />
      </div>

      <MtfOptions
        key={state.status === 'error' ? JSON.stringify(state.values) : state.status}
        idPrefix="schedule"
        mtfName="mtf"
        requireName="require_htf_aligned"
        defaultMtf={values.mtf}
        defaultRequire={values.require_htf_aligned}
        requireError={errors.require_htf_aligned}
      />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <label className={CHECKBOX_LABEL_CLASSES}>
          <input
            type="checkbox"
            name="only_on_change"
            defaultChecked={values.only_on_change}
            className="size-4 rounded border-input"
          />
          Only on change
        </label>
        <label className={CHECKBOX_LABEL_CLASSES}>
          <input
            type="checkbox"
            name="send_hold"
            defaultChecked={values.send_hold}
            className="size-4 rounded border-input"
          />
          Send HOLD verdicts
        </label>
        <label className={CHECKBOX_LABEL_CLASSES}>
          <input
            type="checkbox"
            name="enabled"
            defaultChecked={values.enabled}
            className="size-4 rounded border-input"
          />
          Enabled
        </label>
        <div className="ml-auto flex gap-2">
          {editing && (
            <Button variant="ghost" asChild>
              <Link href="/automation">Cancel</Link>
            </Button>
          )}
          <Button type="submit" disabled={pending}>
            {pending ? 'Saving…' : editing ? 'Save changes' : 'Create schedule'}
          </Button>
        </div>
      </div>
    </form>
  );
}
