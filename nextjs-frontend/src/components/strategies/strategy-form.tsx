'use client';

import Link from 'next/link';
import { useActionState, useEffect, useRef, useState } from 'react';

import { saveStrategyAction } from '@/app/strategies/actions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ConditionInfo } from '@/lib/strategies/catalogue';
import type { FieldErrors, FormMode, StrategyFormValues } from '@/lib/strategies/form';
import { STATUSES, STRATEGY_LIMITS, ZONE_KINDS } from '@/lib/strategies/schema';
import { IDLE_STRATEGY_FORM_STATE } from '@/lib/strategies/state';
import { ConditionBuilder } from './condition-builder';

/**
 * Create, edit or duplicate a strategy. Labelled controls in one form; each invalid field gets its
 * own message linked with `aria-describedby`, and focus moves to the first invalid field (or the
 * form's alert) after a failed submit. A successful save redirects to the list.
 */

const TEXTAREA_CLASSES =
  'min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';
const CHECKBOX_LABEL_CLASSES = 'flex min-h-11 items-center gap-2 text-sm';

const HINTS: Readonly<Record<string, string>> = {
  slug: 'Lowercase letters, digits and hyphens; used in links and schedules. It cannot change later.',
  name: "Letters, digits, spaces and . , % ( ) / & ' -",
  swing_length: `Bars each side of a swing point, ${STRATEGY_LIMITS.swingMin} to ${STRATEGY_LIMITS.swingMax}.`,
  near_atr: `How close counts as near, in ATR, 0 to ${STRATEGY_LIMITS.nearAtrMax}.`,
};

type StrategyFormProps = {
  catalogue: readonly ConditionInfo[];
  initial: StrategyFormValues;
  mode: FormMode;
};

/**
 * The values to show after a failed submit. Params of an off condition are disabled and so never
 * posted; they (and conditions the server could not read) keep their initial values.
 */
function merge(initial: StrategyFormValues, returned: StrategyFormValues): StrategyFormValues {
  const conditions = Object.fromEntries(
    Object.entries(initial.conditions).map(([key, start]) => {
      const back = returned.conditions[key];
      if (back === undefined) return [key, start];
      return [key, back.mode === 'off' ? { ...back, params: start.params } : back];
    })
  );
  return { ...returned, conditions };
}

export function StrategyForm({ catalogue, initial, mode }: StrategyFormProps) {
  const [state, formAction, pending] = useActionState(saveStrategyAction, IDLE_STRATEGY_FORM_STATE);
  const values = state.status === 'error' ? merge(initial, state.values) : initial;
  const errors: FieldErrors = state.status === 'error' ? state.errors : {};
  // `form` holds an error with no field of its own; show it with the form's message.
  const formMessage = state.status === 'error' ? (state.message ?? errors.form) : undefined;
  const formRef = useRef<HTMLFormElement>(null);

  // After a failed submit, land on the first invalid field, else on the form's alert.
  useEffect(() => {
    if (state.status !== 'error') return;
    const form = formRef.current;
    const target =
      form?.querySelector<HTMLElement>('[aria-invalid="true"]') ??
      form?.querySelector<HTMLElement>('[data-form-alert]');
    target?.focus();
  }, [state]);

  const editing = mode === 'edit';
  return (
    <form
      ref={formRef}
      action={formAction}
      aria-label={editing ? `Edit strategy ${initial.name}` : 'New strategy'}
      className="space-y-6"
      noValidate
    >
      <input type="hidden" name="mode" value={mode} />
      {editing && <input type="hidden" name="slug" value={initial.slug} />}
      {formMessage && (
        <p
          role="alert"
          tabIndex={-1}
          data-form-alert
          className="rounded-lg border border-destructive/50 p-3 text-sm text-crit-foreground outline-none"
        >
          {formMessage}
        </p>
      )}
      {/* Remount on each returned set of values so defaults and builder state follow them. */}
      <StrategyFields
        key={JSON.stringify(values)}
        catalogue={catalogue}
        values={values}
        errors={errors}
        editing={editing}
      />
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" asChild>
          <Link href="/strategies">Cancel</Link>
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : editing ? 'Save changes' : 'Create strategy'}
        </Button>
      </div>
    </form>
  );
}

type StrategyFieldsProps = {
  catalogue: readonly ConditionInfo[];
  values: StrategyFormValues;
  errors: FieldErrors;
  editing: boolean;
};

function StrategyFields({ catalogue, values, errors, editing }: StrategyFieldsProps) {
  const [mtf, setMtf] = useState(values.mtf);
  const [requireHtf, setRequireHtf] = useState(values.require_htf_aligned && values.mtf);

  const describedBy = (name: string) =>
    [HINTS[name] ? `strategy-${name}-hint` : null, errors[name] ? `strategy-${name}-error` : null]
      .filter(Boolean)
      .join(' ') || undefined;
  const fieldProps = (name: string) => ({
    id: `strategy-${name}`,
    name,
    'aria-invalid': errors[name] ? true : undefined,
    'aria-describedby': describedBy(name),
  });
  const hint = (name: string) =>
    HINTS[name] ? (
      <p id={`strategy-${name}-hint`} className="mt-1 text-xs text-muted-foreground">
        {HINTS[name]}
      </p>
    ) : null;
  const fieldError = (name: string) =>
    errors[name] ? (
      <p id={`strategy-${name}-error`} className="mt-1 text-xs text-crit-foreground">
        {errors[name]}
      </p>
    ) : null;
  const choiceGroup = (
    name: string,
    legend: string,
    options: readonly string[],
    picked: readonly string[]
  ) => (
    <fieldset aria-describedby={errors[name] ? `strategy-${name}-error` : undefined}>
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      <div className="flex flex-wrap gap-x-4">
        {options.map((option) => (
          <label key={option} className={CHECKBOX_LABEL_CLASSES}>
            <input
              type="checkbox"
              name={name}
              value={option}
              defaultChecked={picked.includes(option)}
              aria-invalid={errors[name] ? true : undefined}
              className="size-4 rounded border-input"
            />
            {option}
          </label>
        ))}
      </div>
      {fieldError(name)}
    </fieldset>
  );

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          {editing ? (
            <>
              <p className="mb-1 text-sm font-medium leading-none">Slug</p>
              <p className="flex h-11 items-center font-mono text-sm">{values.slug}</p>
            </>
          ) : (
            <>
              <Label htmlFor="strategy-slug" className="mb-1 block">
                Slug
              </Label>
              <Input
                {...fieldProps('slug')}
                defaultValue={values.slug}
                maxLength={STRATEGY_LIMITS.slugMax}
                autoComplete="off"
                spellCheck={false}
                required
              />
              {hint('slug')}
              {fieldError('slug')}
            </>
          )}
        </div>
        <div>
          <Label htmlFor="strategy-name" className="mb-1 block">
            Name
          </Label>
          <Input
            {...fieldProps('name')}
            defaultValue={values.name}
            maxLength={STRATEGY_LIMITS.nameMax}
            autoComplete="off"
            required
          />
          {hint('name')}
          {fieldError('name')}
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="strategy-description" className="mb-1 block">
            Description (optional)
          </Label>
          <textarea
            {...fieldProps('description')}
            defaultValue={values.description}
            maxLength={STRATEGY_LIMITS.descriptionMax}
            className={TEXTAREA_CLASSES}
          />
          {fieldError('description')}
        </div>
        <div>
          <Label htmlFor="strategy-swing_length" className="mb-1 block">
            Swing length
          </Label>
          <Input
            {...fieldProps('swing_length')}
            type="number"
            inputMode="numeric"
            min={STRATEGY_LIMITS.swingMin}
            max={STRATEGY_LIMITS.swingMax}
            step={1}
            defaultValue={values.swing_length}
          />
          {hint('swing_length')}
          {fieldError('swing_length')}
        </div>
        <div>
          <Label htmlFor="strategy-near_atr" className="mb-1 block">
            Near (ATR)
          </Label>
          <Input
            {...fieldProps('near_atr')}
            type="number"
            inputMode="decimal"
            min={0}
            max={STRATEGY_LIMITS.nearAtrMax}
            step="any"
            defaultValue={values.near_atr}
          />
          {hint('near_atr')}
          {fieldError('near_atr')}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {choiceGroup('zone_kinds', 'Zone kinds', ZONE_KINDS, values.zone_kinds)}
        {choiceGroup('statuses', 'Statuses', STATUSES, values.statuses)}
      </div>

      <fieldset>
        <legend className="mb-1 text-sm font-medium">Higher timeframe</legend>
        <div className="flex flex-wrap gap-x-6">
          <label className={CHECKBOX_LABEL_CLASSES}>
            <input
              type="checkbox"
              name="mtf"
              checked={mtf}
              onChange={(event) => {
                setMtf(event.target.checked);
                if (!event.target.checked) setRequireHtf(false);
              }}
              className="size-4 rounded border-input"
            />
            Include higher timeframe context
          </label>
          <label className={CHECKBOX_LABEL_CLASSES}>
            <input
              type="checkbox"
              id="strategy-require_htf_aligned"
              name="require_htf_aligned"
              checked={requireHtf}
              disabled={!mtf}
              onChange={(event) => setRequireHtf(event.target.checked)}
              aria-invalid={errors.require_htf_aligned ? true : undefined}
              aria-describedby={
                errors.require_htf_aligned
                  ? 'strategy-require_htf_aligned-hint strategy-require_htf_aligned-error'
                  : 'strategy-require_htf_aligned-hint'
              }
              className="size-4 rounded border-input"
            />
            Only rows the higher timeframe confirms
          </label>
        </div>
        <p id="strategy-require_htf_aligned-hint" className="text-xs text-muted-foreground">
          Needs higher timeframe context on.
        </p>
        {fieldError('require_htf_aligned')}
      </fieldset>

      <ConditionBuilder
        catalogue={catalogue}
        conditions={values.conditions}
        minScore={values.min_score}
        errors={errors}
      />
    </div>
  );
}
