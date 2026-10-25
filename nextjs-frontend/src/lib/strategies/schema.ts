import { z } from 'zod';

/**
 * The strategy request bodies as the API validates them (`StrategyCreate` / `StrategyUpdate` and
 * the `Strategy` cross-field rules), so a bad value is caught before any request. Condition params
 * are checked against each condition's own `params_schema` in `form.ts`; here they only get the
 * API's generic bounds. No `server-only`: the form and the server actions share it.
 */

export const STRATEGY_LIMITS = {
  slugMax: 32,
  nameMax: 64,
  descriptionMax: 280,
  conditionsMax: 12,
  paramsMax: 8,
  paramStringMax: 32,
  paramMagnitude: 1e9,
  swingMin: 1,
  swingMax: 100,
  nearAtrMax: 5,
  customMax: 50,
} as const;

export const ZONE_KINDS = ['FVG', 'OB'] as const;
export const STATUSES = ['TOUCHING', 'NEAR'] as const;
export const BUILTIN_SLUGS = [
  'smc-default',
  'fresh-ob-trend',
  'fvg-ote-reversal',
  'htf-aligned-touch',
  'valid-ob',
] as const;

export const DEFAULT_SWING_LENGTH = 10;
export const DEFAULT_NEAR_ATR = 0.5;

export const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;
export const CONDITION_KEY_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;
const TEXT_PATTERN = /^[A-Za-z0-9 .,%()/&'-]*$/;
const HAS_ALNUM = /[A-Za-z0-9]/;
export const PARAM_STRING_PATTERN = /^[A-Za-z0-9_.-]*$/;
export const PARAM_STRING_MESSAGE = `Use at most ${STRATEGY_LIMITS.paramStringMax} letters, digits, _ . - only.`;

export const SLUG_MESSAGE =
  'Use 1 to 32 lowercase letters, digits or hyphens, not starting with a hyphen.';
export const TEXT_ALPHABET_MESSAGE = "Use letters, digits, spaces and . , % ( ) / & ' - only.";
export const BUILTIN_SLUG_MESSAGE = 'That slug belongs to a built-in strategy. Choose another.';
const NAME_MESSAGE = `Enter a name of at most ${STRATEGY_LIMITS.nameMax} characters.`;
const SWING_MESSAGE = `Enter a whole number from ${STRATEGY_LIMITS.swingMin} to ${STRATEGY_LIMITS.swingMax}.`;
const NEAR_MESSAGE = `Enter a number from 0 to ${STRATEGY_LIMITS.nearAtrMax}.`;
const MIN_SCORE_MESSAGE = 'Enter a whole number of at least 0.';
const LIST_MESSAGE = `Use at most ${STRATEGY_LIMITS.conditionsMax} conditions.`;

const BUILTIN_SET: ReadonlySet<string> = new Set(BUILTIN_SLUGS);

export function isBuiltinSlug(slug: string): boolean {
  return BUILTIN_SET.has(slug);
}

export const slugSchema = z.string().regex(SLUG_PATTERN, SLUG_MESSAGE);

const paramValueSchema = z.union([
  z.boolean(),
  z
    .number()
    .finite()
    .refine((value) => Math.abs(value) <= STRATEGY_LIMITS.paramMagnitude, {
      message: 'Enter a smaller number.',
    }),
  z
    .string()
    .max(STRATEGY_LIMITS.paramStringMax, PARAM_STRING_MESSAGE)
    .regex(PARAM_STRING_PATTERN, PARAM_STRING_MESSAGE),
]);

export const conditionRefSchema = z
  .object({
    key: z.string().regex(CONDITION_KEY_PATTERN),
    params: z
      .record(z.string().regex(CONDITION_KEY_PATTERN), paramValueSchema)
      .refine((params) => Object.keys(params).length <= STRATEGY_LIMITS.paramsMax, {
        message: `Use at most ${STRATEGY_LIMITS.paramsMax} parameters.`,
      }),
  })
  .strict();

const conditionListSchema = z
  .array(conditionRefSchema)
  .max(STRATEGY_LIMITS.conditionsMax, LIST_MESSAGE);

/** A `zone_kinds` / `statuses` list: at least one, no duplicates. */
function choiceList<T extends readonly [string, ...string[]]>(options: T, message: string) {
  return z
    .array(z.enum(options))
    .min(1, message)
    .refine((values) => new Set(values).size === values.length, { message });
}

const definitionShape = {
  name: z
    .string()
    .trim()
    .min(1, NAME_MESSAGE)
    .max(STRATEGY_LIMITS.nameMax, NAME_MESSAGE)
    .regex(TEXT_PATTERN, TEXT_ALPHABET_MESSAGE)
    .regex(HAS_ALNUM, 'The name needs at least one letter or digit.'),
  description: z
    .string()
    .trim()
    .max(
      STRATEGY_LIMITS.descriptionMax,
      `Use at most ${STRATEGY_LIMITS.descriptionMax} characters.`
    )
    .regex(TEXT_PATTERN, TEXT_ALPHABET_MESSAGE),
  zone_kinds: choiceList(ZONE_KINDS, 'Choose at least one zone kind.'),
  swing_length: z
    .number({ invalid_type_error: SWING_MESSAGE, required_error: SWING_MESSAGE })
    .int(SWING_MESSAGE)
    .min(STRATEGY_LIMITS.swingMin, SWING_MESSAGE)
    .max(STRATEGY_LIMITS.swingMax, SWING_MESSAGE),
  near_atr: z
    .number({ invalid_type_error: NEAR_MESSAGE, required_error: NEAR_MESSAGE })
    .finite(NEAR_MESSAGE)
    .min(0, NEAR_MESSAGE)
    .max(STRATEGY_LIMITS.nearAtrMax, NEAR_MESSAGE),
  require: conditionListSchema,
  score: conditionListSchema,
  min_score: z
    .number({ invalid_type_error: MIN_SCORE_MESSAGE, required_error: MIN_SCORE_MESSAGE })
    .int(MIN_SCORE_MESSAGE)
    .min(0, MIN_SCORE_MESSAGE),
  statuses: choiceList(STATUSES, 'Choose at least one status.'),
  mtf: z.boolean(),
  require_htf_aligned: z.boolean(),
};

type Definition = z.infer<z.ZodObject<typeof definitionShape>>;

/** The `Strategy` model's cross-field rules. */
function checkCrossFields(body: Definition, ctx: z.RefinementCtx): void {
  const seen = new Set<string>();
  for (const [list, refs] of [
    ['require', body.require],
    ['score', body.score],
  ] as const) {
    refs.forEach((ref, index) => {
      if (seen.has(ref.key)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [list, index, 'key'],
          message: 'A condition can be used only once.',
        });
      }
      seen.add(ref.key);
    });
  }
  if (body.min_score > body.score.length) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['min_score'],
      message: `Enter a whole number from 0 to ${body.score.length} (the scored conditions).`,
    });
  }
  if (body.require_htf_aligned && !body.mtf) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['require_htf_aligned'],
      message: 'Include higher timeframe context first.',
    });
  }
}

/** `PUT /strategies/{slug}`: no slug, no builtin, nothing extra. */
export const strategyUpdateSchema = z
  .object(definitionShape)
  .strict()
  .superRefine(checkCrossFields);

/** `POST /strategies`: the definition plus a slug that is not a built-in one. */
export const strategyCreateSchema = z
  .object({ ...definitionShape, slug: slugSchema })
  .strict()
  .superRefine((body, ctx) => {
    checkCrossFields(body, ctx);
    if (isBuiltinSlug(body.slug)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['slug'], message: BUILTIN_SLUG_MESSAGE });
    }
  });

export type StrategyUpdateBody = z.infer<typeof strategyUpdateSchema>;
export type StrategyCreateBody = z.infer<typeof strategyCreateSchema>;
