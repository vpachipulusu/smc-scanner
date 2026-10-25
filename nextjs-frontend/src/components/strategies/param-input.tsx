import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ParamField } from '@/lib/strategies/catalogue';
import { STRATEGY_LIMITS } from '@/lib/strategies/schema';

/**
 * One condition parameter, rendered from its `params_schema` property: a select for an enum, a
 * number input with the schema's bounds, a checkbox or a short text input. Disabled (and so not
 * submitted) while its condition is off.
 */

export const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50';

type ParamInputProps = {
  field: ParamField;
  id: string;
  name: string;
  defaultValue: string;
  disabled: boolean;
  error?: string;
};

function hintFor(field: ParamField): string | null {
  if (field.kind !== 'integer' && field.kind !== 'number') return null;
  if (field.min !== undefined && field.max !== undefined) return `${field.min} to ${field.max}`;
  if (field.min !== undefined) return `at least ${field.min}`;
  if (field.max !== undefined) return `at most ${field.max}`;
  return null;
}

export function ParamInput({ field, id, name, defaultValue, disabled, error }: ParamInputProps) {
  const errorId = `${id}-error`;
  const hint = hintFor(field);
  const hintId = `${id}-hint`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ');
  const common = {
    id,
    name,
    disabled,
    'aria-required': field.required && field.kind !== 'boolean' ? true : undefined,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': describedBy || undefined,
  };

  if (field.kind === 'boolean') {
    return (
      <div>
        <label htmlFor={id} className="flex min-h-11 items-center gap-2 text-sm">
          <input
            {...common}
            type="checkbox"
            value="true"
            defaultChecked={defaultValue === 'true'}
            className="size-4 rounded border-input"
          />
          {field.label}
        </label>
        {error && (
          <p id={errorId} className="mt-1 text-xs text-crit-foreground">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <Label htmlFor={id} className="mb-1 block text-xs">
        {field.label}
        {field.required ? '' : ' (optional)'}
      </Label>
      {field.kind === 'enum' ? (
        <select {...common} defaultValue={defaultValue} className={SELECT_CLASSES}>
          {!field.required && <option value="">Not set</option>}
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : field.kind === 'string' ? (
        <Input
          {...common}
          defaultValue={defaultValue}
          maxLength={STRATEGY_LIMITS.paramStringMax}
          autoComplete="off"
          spellCheck={false}
        />
      ) : (
        <Input
          {...common}
          type="number"
          inputMode={field.kind === 'integer' ? 'numeric' : 'decimal'}
          min={field.min}
          max={field.max}
          step={field.kind === 'integer' ? 1 : 'any'}
          defaultValue={defaultValue}
        />
      )}
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="mt-1 text-xs text-crit-foreground">
          {error}
        </p>
      )}
    </div>
  );
}
