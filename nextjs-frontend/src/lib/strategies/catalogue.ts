import { CONDITION_KEY_PATTERN, STRATEGY_LIMITS } from './schema';

/**
 * The condition catalogue from `GET /config` (`conditions`), turned into what the builder renders:
 * one input per property of each condition's `params_schema`. Nothing here hard-codes a condition
 * key; a schema this parser cannot render makes the whole catalogue invalid, so a condition is
 * never silently dropped from a strategy that uses it.
 */

type ParamBase = { name: string; label: string; required: boolean };

export type NumberParamField = ParamBase & {
  kind: 'integer' | 'number';
  min?: number;
  max?: number;
  defaultValue?: number;
};
export type EnumParamField = ParamBase & {
  kind: 'enum';
  options: readonly string[];
  defaultValue?: string;
};
export type BooleanParamField = ParamBase & { kind: 'boolean'; defaultValue?: boolean };
export type StringParamField = ParamBase & { kind: 'string'; defaultValue?: string };

export type ParamField = NumberParamField | EnumParamField | BooleanParamField | StringParamField;

export type ConditionInfo = {
  key: string;
  label: string;
  params: readonly ParamField[];
};

const MAX_LABEL_CHARS = 120;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const finite = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

function isShortString(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value.length <= STRATEGY_LIMITS.paramStringMax
  );
}

function labelOf(property: Record<string, unknown>, name: string): string {
  const title = property.title;
  return typeof title === 'string' && title.trim() !== ''
    ? title.trim().slice(0, MAX_LABEL_CHARS)
    : name;
}

function paramField(name: string, property: unknown, required: boolean): ParamField | null {
  if (!CONDITION_KEY_PATTERN.test(name) || !isRecord(property)) return null;
  const base = { name, label: labelOf(property, name), required };
  if (Array.isArray(property.enum)) {
    const options = property.enum;
    if (options.length === 0 || !options.every(isShortString)) return null;
    const fallback = property.default;
    return {
      ...base,
      kind: 'enum',
      options,
      defaultValue:
        typeof fallback === 'string' && options.includes(fallback) ? fallback : undefined,
    };
  }
  switch (property.type) {
    case 'integer':
    case 'number':
      return {
        ...base,
        kind: property.type,
        min: finite(property.minimum),
        max: finite(property.maximum),
        defaultValue: finite(property.default),
      };
    case 'boolean':
      return {
        ...base,
        kind: 'boolean',
        defaultValue: typeof property.default === 'boolean' ? property.default : undefined,
      };
    case 'string':
      return {
        ...base,
        kind: 'string',
        defaultValue: isShortString(property.default) ? property.default : undefined,
      };
    default:
      return null;
  }
}

/** The inputs for one `params_schema`; null when it has a property the builder cannot render. */
export function paramFieldsFromSchema(schema: unknown): ParamField[] | null {
  if (!isRecord(schema)) return null;
  const properties = schema.properties ?? {};
  if (!isRecord(properties)) return null;
  const required = Array.isArray(schema.required) ? schema.required : [];
  const fields: ParamField[] = [];
  for (const [name, property] of Object.entries(properties)) {
    const field = paramField(name, property, required.includes(name));
    if (field === null) return null;
    fields.push(field);
  }
  return fields.length <= STRATEGY_LIMITS.paramsMax ? fields : null;
}

/** One `ConditionInfoOut` from the API, checked; null when it is not usable. */
export function toConditionInfo(raw: unknown): ConditionInfo | null {
  if (!isRecord(raw)) return null;
  const { key, label } = raw;
  if (typeof key !== 'string' || !CONDITION_KEY_PATTERN.test(key)) return null;
  if (typeof label !== 'string' || label.trim() === '') return null;
  const params = paramFieldsFromSchema(raw.params_schema);
  if (params === null) return null;
  return { key, label: label.trim().slice(0, MAX_LABEL_CHARS), params };
}

/** The label of a condition key, or the key itself when the catalogue does not know it. */
export function conditionLabel(catalogue: readonly ConditionInfo[], key: string): string {
  return catalogue.find((info) => info.key === key)?.label ?? key;
}
