'use client';

import Link from 'next/link';
import { useActionState, useEffect, useRef } from 'react';

import { saveJournalAction } from '@/app/journal/actions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  LIMITS,
  SIDES,
  TIMEFRAMES,
  type JournalFieldName,
  type JournalFormValues,
} from '@/lib/journal/form';
import { IDLE_JOURNAL_FORM_STATE } from '@/lib/journal/state';

/**
 * Add or edit a journal entry. Plain labelled controls in a form, so it works with the keyboard
 * alone; each invalid field gets its own message, linked with `aria-describedby`, and focus moves
 * to the first invalid field after a failed submit. Times are UTC.
 */

const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const TEXTAREA_CLASSES =
  'min-h-24 w-full rounded-xl border border-input bg-background px-4 py-2.5 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const HINTS: Partial<Record<JournalFieldName, string>> = {
  opened_at: 'UTC time.',
  closed_at: 'UTC time. Set together with the exit price.',
  pnl_currency: 'Optional, for a closed trade. Negative for a loss.',
};

export function JournalForm({
  initialValues,
  entryId,
}: {
  initialValues: JournalFormValues;
  /** Set when editing; the action then updates this entry instead of creating one. */
  entryId?: number;
}) {
  const [state, formAction, pending] = useActionState(saveJournalAction, IDLE_JOURNAL_FORM_STATE);
  const values = state.status === 'error' ? state.values : initialValues;
  const errors = state.status === 'error' ? state.errors : {};
  const editing = entryId !== undefined;
  const formRef = useRef<HTMLFormElement>(null);

  // After a failed submit, land on the first invalid field.
  useEffect(() => {
    if (state.status === 'error') {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }
  }, [state]);

  const describedBy = (name: JournalFieldName) =>
    [HINTS[name] ? `journal-${name}-hint` : null, errors[name] ? `journal-${name}-error` : null]
      .filter(Boolean)
      .join(' ') || undefined;
  const fieldProps = (name: JournalFieldName) => ({
    id: `journal-${name}`,
    name,
    'aria-invalid': errors[name] ? true : undefined,
    'aria-describedby': describedBy(name),
  });
  const fieldError = (name: JournalFieldName) =>
    errors[name] ? (
      <p id={`journal-${name}-error`} className="mt-1 text-xs text-crit-foreground">
        {errors[name]}
      </p>
    ) : null;
  const hint = (name: JournalFieldName) =>
    HINTS[name] ? (
      <p id={`journal-${name}-hint`} className="mt-1 text-xs text-muted-foreground">
        {HINTS[name]}
      </p>
    ) : null;
  const decimal = (
    name: JournalFieldName,
    label: string,
    required = false,
    placeholder?: string
  ) => (
    <div>
      <Label htmlFor={`journal-${name}`} className="mb-1 block">
        {label}
      </Label>
      <Input
        {...fieldProps(name)}
        defaultValue={values[name]}
        inputMode="decimal"
        placeholder={placeholder}
        autoComplete="off"
        required={required}
      />
      {hint(name)}
      {fieldError(name)}
    </div>
  );
  const dateTime = (name: 'opened_at' | 'closed_at', label: string, required = false) => (
    <div>
      <Label htmlFor={`journal-${name}`} className="mb-1 block">
        {label}
      </Label>
      <Input
        {...fieldProps(name)}
        type="datetime-local"
        defaultValue={values[name]}
        required={required}
      />
      {hint(name)}
      {fieldError(name)}
    </div>
  );

  return (
    <form
      ref={formRef}
      action={formAction}
      aria-label={editing ? 'Edit journal entry' : 'New journal entry'}
      className="space-y-4"
      noValidate
    >
      {editing && <input type="hidden" name="id" value={entryId} />}
      <input type="hidden" name="analysis_id" value={values.analysis_id} />
      {state.status === 'error' && state.message && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 p-3 text-sm text-crit-foreground"
        >
          {state.message}
        </p>
      )}
      {values.analysis_id !== '' && (
        <p className="text-sm text-muted-foreground">Linked to analysis #{values.analysis_id}.</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label htmlFor="journal-symbol" className="mb-1 block">
            Symbol
          </Label>
          <Input
            {...fieldProps('symbol')}
            defaultValue={values.symbol}
            placeholder="EURUSD"
            autoComplete="off"
            spellCheck={false}
            required
          />
          {fieldError('symbol')}
        </div>
        <div>
          <Label htmlFor="journal-timeframe" className="mb-1 block">
            Timeframe
          </Label>
          <select
            key={values.timeframe}
            {...fieldProps('timeframe')}
            defaultValue={values.timeframe}
            className={SELECT_CLASSES}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
          {fieldError('timeframe')}
        </div>
        <div>
          <Label htmlFor="journal-side" className="mb-1 block">
            Side
          </Label>
          {/* Keyed by value: React 19 resets the form after an action and ignores a changed
              defaultValue on a select, so remount to keep the submitted choice. */}
          <select
            key={values.side}
            {...fieldProps('side')}
            defaultValue={values.side}
            className={SELECT_CLASSES}
          >
            {SIDES.map((side) => (
              <option key={side} value={side}>
                {side}
              </option>
            ))}
          </select>
          {fieldError('side')}
        </div>
        {decimal('size', 'Size', false, 'optional')}
        {decimal('entry', 'Entry price', true)}
        {decimal('stop', 'Stop price', true)}
        {decimal('exit', 'Exit price')}
        {decimal('pnl_currency', 'Result (currency)')}
        {dateTime('opened_at', 'Opened (UTC)', true)}
        {dateTime('closed_at', 'Closed (UTC)')}
        <div className="sm:col-span-2">
          <Label htmlFor="journal-notes" className="mb-1 block">
            Notes
          </Label>
          <textarea
            {...fieldProps('notes')}
            defaultValue={values.notes}
            maxLength={LIMITS.notesMax}
            className={TEXTAREA_CLASSES}
          />
          {fieldError('notes')}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        {editing && (
          <Button variant="ghost" asChild>
            <Link href="/journal">Cancel</Link>
          </Button>
        )}
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : editing ? 'Save changes' : 'Add entry'}
        </Button>
      </div>
    </form>
  );
}
