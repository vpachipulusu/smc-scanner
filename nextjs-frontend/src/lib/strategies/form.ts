import type { z } from 'zod';

import type { StrategyOut } from '@/lib/api/strategies-write';
import type { ConditionInfo, ParamField } from './catalogue';
import {
  DEFAULT_NEAR_ATR,
  DEFAULT_SWING_LENGTH,
  PARAM_STRING_MESSAGE,
  PARAM_STRING_PATTERN,
  STATUSES,
  STRATEGY_LIMITS,
  ZONE_KINDS,
  strategyCreateSchema,
  strategyUpdateSchema,
  type StrategyUpdateBody,
} from './schema';

/**
 * Reading, prefilling and validating the strategy form. Only allow-listed fields are read: the
 * fixed definition fields plus `cond.<key>` and `param.<key>.<name>` for the catalogue's own keys,
 * so a posted unknown condition or param is ignored. Params are checked against their
 * `params_schema`; the body then goes through the zod schema that mirrors the API.
 */

export type ConditionMode = 'off' | 'require' | 'score';
export const CONDITION_MODES: readonly ConditionMode[] = ['off', 'require', 'score'];

export type ConditionValue = { mode: ConditionMode; params: Readonly<Record<string, string>> };

export type StrategyFormValues = {
  slug: string;
  name: string;
  description: string;
  zone_kinds: readonly string[];
  swing_length: string;
  near_atr: string;
  statuses: readonly string[];
  min_score: string;
  mtf: boolean;
  require_htf_aligned: boolean;
  conditions: Readonly<Record<string, ConditionValue>>;
};

/** Keyed by form field name: `name`, `cond.<key>`, `param.<key>.<name>`, `conditions`, ... */
export type FieldErrors = Readonly<Record<string, string>>;

export type ParsedStrategy =
  | { ok: true; body: StrategyUpdateBody; slug: string; values: StrategyFormValues }
  | { ok: false; errors: FieldErrors; values: StrategyFormValues };

export type FormMode = 'create' | 'edit';

export const MAX_FIELD_LENGTH = 2000;
const CHECKBOX_ON = ['on', '1', 'true'];
const INTEGER_PATTERN = /^-?\d{1,10}$/;
// Wide enough for any stored number to round-trip (e.g. 1e-7, 0.3333333333333333).
const DECIMAL_PATTERN = /^-?\d{1,10}(?:\.\d{1,17})?(?:[eE][-+]?\d{1,3})?$/;
const COPY_SUFFIX = ' (copy)';
const MAX_COPY_ATTEMPTS = 50;

export const condField = (key: string) => `cond.${key}`;
export const paramField = (key: string, name: string) => `param.${key}.${name}`;

function defaultParam(field: ParamField): string {
  if (field.defaultValue !== undefined) return String(field.defaultValue);
  // An optional enum without a default starts unset, so saving never invents a value.
  if (field.kind === 'enum' && field.required) return field.options[0] ?? '';
  return '';
}

function conditionValues(
  catalogue: readonly ConditionInfo[],
  strategy?: Pick<StrategyOut, 'require' | 'score'>
): Record<string, ConditionValue> {
  const entries = catalogue.map((info): [string, ConditionValue] => {
    const required = strategy?.require.find((ref) => ref.key === info.key);
    const scored = strategy?.score.find((ref) => ref.key === info.key);
    const ref = required ?? scored;
    const mode: ConditionMode = required ? 'require' : scored ? 'score' : 'off';
    const params = Object.fromEntries(
      info.params.map((field) => {
        // Own properties only: a param named like an Object.prototype member must not read it.
        const value =
          ref && Object.hasOwn(ref.params, field.name) ? ref.params[field.name] : undefined;
        return [field.name, value === undefined ? defaultParam(field) : String(value)];
      })
    );
    return [info.key, { mode, params }];
  });
  return Object.fromEntries(entries);
}

export function emptyFormValues(catalogue: readonly ConditionInfo[]): StrategyFormValues {
  return {
    slug: '',
    name: '',
    description: '',
    zone_kinds: [...ZONE_KINDS],
    swing_length: String(DEFAULT_SWING_LENGTH),
    near_atr: String(DEFAULT_NEAR_ATR),
    statuses: [...STATUSES],
    min_score: '0',
    mtf: false,
    require_htf_aligned: false,
    conditions: conditionValues(catalogue),
  };
}

export function valuesFromStrategy(
  strategy: StrategyOut,
  catalogue: readonly ConditionInfo[]
): StrategyFormValues {
  return {
    slug: strategy.slug,
    name: strategy.name,
    description: strategy.description,
    zone_kinds: [...strategy.zone_kinds],
    swing_length: String(strategy.swing_length),
    near_atr: String(strategy.near_atr),
    statuses: [...strategy.statuses],
    min_score: String(strategy.min_score),
    mtf: strategy.mtf,
    require_htf_aligned: strategy.require_htf_aligned,
    conditions: conditionValues(catalogue, strategy),
  };
}

/** A free slug for a copy of `slug`: `<slug>-copy`, then `<slug>-copy-2`, ... */
export function copySlug(slug: string, taken: ReadonlySet<string>): string {
  for (let attempt = 1; attempt <= MAX_COPY_ATTEMPTS; attempt += 1) {
    const suffix = attempt === 1 ? '-copy' : `-copy-${attempt}`;
    const base = slug.slice(0, STRATEGY_LIMITS.slugMax - suffix.length).replace(/-+$/, '');
    const candidate = `${base}${suffix}`;
    if (!taken.has(candidate)) return candidate;
  }
  return '';
}

export function copyName(name: string): string {
  return `${name.slice(0, STRATEGY_LIMITS.nameMax - COPY_SUFFIX.length).trimEnd()}${COPY_SUFFIX}`;
}

/** The form prefilled from `strategy` (built-in or custom) with a new, free slug and name. */
export function duplicateValues(
  strategy: StrategyOut,
  catalogue: readonly ConditionInfo[],
  taken: ReadonlySet<string>
): StrategyFormValues {
  return {
    ...valuesFromStrategy(strategy, catalogue),
    slug: copySlug(strategy.slug, taken),
    name: copyName(strategy.name),
  };
}

function text(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === 'string' ? value.slice(0, MAX_FIELD_LENGTH).trim() : '';
}

function flag(form: FormData, key: string): boolean {
  const value = form.get(key);
  return typeof value === 'string' && CHECKBOX_ON.includes(value);
}

function choices(form: FormData, key: string, options: readonly string[]): string[] {
  const picked = new Set(form.getAll(key).filter((value) => typeof value === 'string'));
  return options.filter((option) => picked.has(option));
}

function readMode(form: FormData, key: string): ConditionMode {
  const value = form.get(condField(key));
  return CONDITION_MODES.find((mode) => mode === value) ?? 'off';
}

/** The submitted values as the form should show them again after an error. */
export function readFormValues(
  form: FormData,
  catalogue: readonly ConditionInfo[]
): StrategyFormValues {
  const conditions = Object.fromEntries(
    catalogue.map((info): [string, ConditionValue] => [
      info.key,
      {
        mode: readMode(form, info.key),
        params: Object.fromEntries(
          info.params.map((field) => [
            field.name,
            field.kind === 'boolean'
              ? String(flag(form, paramField(info.key, field.name)))
              : text(form, paramField(info.key, field.name)),
          ])
        ),
      },
    ])
  );
  return {
    slug: text(form, 'slug'),
    name: text(form, 'name'),
    description: text(form, 'description'),
    zone_kinds: choices(form, 'zone_kinds', ZONE_KINDS),
    swing_length: text(form, 'swing_length'),
    near_atr: text(form, 'near_atr'),
    statuses: choices(form, 'statuses', STATUSES),
    min_score: text(form, 'min_score'),
    mtf: flag(form, 'mtf'),
    require_htf_aligned: flag(form, 'require_htf_aligned'),
    conditions,
  };
}

function toNumber(raw: string, pattern: RegExp): number {
  return pattern.test(raw) ? Number(raw) : Number.NaN;
}

function rangeMessage(field: Extract<ParamField, { kind: 'integer' | 'number' }>): string {
  const what = field.kind === 'integer' ? 'a whole number' : 'a number';
  if (field.min !== undefined && field.max !== undefined) {
    return `Enter ${what} from ${field.min} to ${field.max}.`;
  }
  if (field.min !== undefined) return `Enter ${what} of at least ${field.min}.`;
  if (field.max !== undefined) return `Enter ${what} of at most ${field.max}.`;
  return `Enter ${what}.`;
}

type ParamResult = { value?: string | number | boolean; error?: string };

/** One param from its text against its schema; `{}` (no value, no error) means "omit it". */
export function parseParam(field: ParamField, raw: string): ParamResult {
  if (field.kind === 'boolean') {
    const checked = raw === 'true';
    // An unchecked optional flag without a default is left unset rather than saved as false.
    const unset = !checked && !field.required && field.defaultValue === undefined;
    return unset ? {} : { value: checked };
  }
  if (raw === '') return field.required ? { error: 'Enter a value.' } : {};
  switch (field.kind) {
    case 'enum':
      return field.options.includes(raw) ? { value: raw } : { error: 'Choose one of the options.' };
    case 'string':
      return raw.length <= STRATEGY_LIMITS.paramStringMax && PARAM_STRING_PATTERN.test(raw)
        ? { value: raw }
        : { error: PARAM_STRING_MESSAGE };
    default: {
      const value = toNumber(raw, field.kind === 'integer' ? INTEGER_PATTERN : DECIMAL_PATTERN);
      const outside =
        Number.isNaN(value) ||
        (field.min !== undefined && value < field.min) ||
        (field.max !== undefined && value > field.max);
      return outside ? { error: rangeMessage(field) } : { value };
    }
  }
}

type Ref = { key: string; params: Record<string, string | number | boolean> };

function collectConditions(values: StrategyFormValues, catalogue: readonly ConditionInfo[]) {
  const errors: Record<string, string> = {};
  const require: Ref[] = [];
  const score: Ref[] = [];
  for (const info of catalogue) {
    const condition = values.conditions[info.key];
    if (!condition || condition.mode === 'off') continue;
    const params: Record<string, string | number | boolean> = {};
    for (const field of info.params) {
      const result = parseParam(field, condition.params[field.name] ?? '');
      if (result.error) errors[paramField(info.key, field.name)] = result.error;
      else if (result.value !== undefined) params[field.name] = result.value;
    }
    (condition.mode === 'require' ? require : score).push({ key: info.key, params });
  }
  return { errors, require, score };
}

const TOP_LEVEL_FIELDS = new Set([
  'slug',
  'name',
  'description',
  'zone_kinds',
  'swing_length',
  'near_atr',
  'statuses',
  'min_score',
  'require_htf_aligned',
]);

/** The form field for a condition-list issue: the param input, the mode group or the list. */
function conditionIssueField(path: readonly (string | number)[], refs: readonly Ref[]): string {
  const [, index, part, name] = path;
  const ref = typeof index === 'number' ? refs[index] : undefined;
  if (!ref) return 'conditions';
  return part === 'params' && typeof name === 'string'
    ? paramField(ref.key, name)
    : condField(ref.key);
}

/** Zod issues as form field errors; anything without a field of its own lands on `form`. */
function issueErrors(issues: readonly z.ZodIssue[], lists: Record<string, readonly Ref[]>) {
  const errors: Record<string, string> = {};
  for (const issue of issues) {
    const head = issue.path[0];
    const field =
      head === 'require' || head === 'score'
        ? conditionIssueField(issue.path, lists[head])
        : typeof head === 'string' && TOP_LEVEL_FIELDS.has(head)
          ? head
          : 'form';
    errors[field] ??= issue.message;
  }
  return errors;
}

/** Validates a submitted form into an API body (plus the slug), or field errors plus the values. */
export function parseStrategyForm(
  form: FormData,
  catalogue: readonly ConditionInfo[],
  mode: FormMode
): ParsedStrategy {
  const values = readFormValues(form, catalogue);
  const { errors: paramErrors, require, score } = collectConditions(values, catalogue);
  const definition = {
    name: values.name,
    description: values.description,
    zone_kinds: values.zone_kinds,
    swing_length: toNumber(values.swing_length, INTEGER_PATTERN),
    near_atr: toNumber(values.near_atr, DECIMAL_PATTERN),
    require,
    score,
    min_score: values.min_score === '' ? 0 : toNumber(values.min_score, INTEGER_PATTERN),
    statuses: values.statuses,
    mtf: values.mtf,
    require_htf_aligned: values.require_htf_aligned,
  };
  const parsed =
    mode === 'create'
      ? strategyCreateSchema.safeParse({ ...definition, slug: values.slug })
      : strategyUpdateSchema.safeParse(definition);
  const errors = {
    ...paramErrors,
    ...(parsed.success ? {} : issueErrors(parsed.error.issues, { require, score })),
  };
  if (!parsed.success || Object.keys(errors).length > 0) {
    return { ok: false, errors, values };
  }
  const { slug: _slug, ...body }: StrategyUpdateBody & { slug?: string } = parsed.data;
  return { ok: true, body, slug: values.slug, values };
}
