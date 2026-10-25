'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';

import {
  addStrategy,
  editStrategy,
  fetchConditionCatalogue,
  removeStrategy,
} from '@/lib/api/strategies-write';
import {
  STRATEGIES_REQUEST_FAILED_MESSAGE,
  STRATEGY_BUILTIN_MESSAGE,
  STRATEGY_SLUG_TAKEN_MESSAGE,
} from '@/lib/api/strategies-write-messages';
import {
  parseStrategyForm,
  readFormValues,
  type FormMode,
  type StrategyFormValues,
} from '@/lib/strategies/form';
import { SLUG_PATTERN, isBuiltinSlug } from '@/lib/strategies/schema';
import type { StrategyFormState, StrategyRowState } from '@/lib/strategies/state';

/**
 * Server actions for the /strategies pages. Only allow-listed form fields are read and validated
 * (see `lib/strategies/form.ts`, which mirrors the API rules); the API is reached through the
 * server-only wrappers, and every failure comes back as one of their fixed messages.
 */

const PAGE = '/strategies';
const BAD_SLUG_MESSAGE = 'That strategy slug is not valid.';

type Outcome<T> = { success: true; data: T } | { success: false; error: string; status?: number };

/** Runs a wrapper call; anything it throws becomes the generic fixed message. */
async function guarded<T>(call: () => Promise<Outcome<T>>): Promise<Outcome<T>> {
  try {
    return await call();
  } catch {
    return { success: false, error: STRATEGIES_REQUEST_FAILED_MESSAGE };
  }
}

function formError(message: string, values: StrategyFormValues): StrategyFormState {
  return { status: 'error', message, errors: {}, values };
}

function readSlug(raw: FormDataEntryValue | null): string | null {
  return typeof raw === 'string' && SLUG_PATTERN.test(raw) ? raw : null;
}

/** Create (`mode=create`, slug from the form) or update (`mode=edit`, slug fixed) a strategy. */
export async function saveStrategyAction(
  _previous: StrategyFormState,
  formData: FormData
): Promise<StrategyFormState> {
  const mode: FormMode = formData.get('mode') === 'edit' ? 'edit' : 'create';
  // Before the catalogue is known no condition field can be read; keep the rest of what was typed.
  const typed = () => readFormValues(formData, []);
  const editSlug = mode === 'edit' ? readSlug(formData.get('slug')) : null;
  if (mode === 'edit' && editSlug === null) return formError(BAD_SLUG_MESSAGE, typed());
  if (editSlug !== null && isBuiltinSlug(editSlug)) {
    return formError(STRATEGY_BUILTIN_MESSAGE, typed());
  }

  const catalogue = await guarded(fetchConditionCatalogue);
  if (!catalogue.success) return formError(catalogue.error, typed());

  const parsed = parseStrategyForm(formData, catalogue.data, mode);
  if (!parsed.ok) return { status: 'error', errors: parsed.errors, values: parsed.values };

  const slug = editSlug ?? parsed.slug;
  const result = await guarded(() =>
    editSlug === null ? addStrategy({ ...parsed.body, slug }) : editStrategy(editSlug, parsed.body)
  );
  if (!result.success) {
    const values = { ...parsed.values, slug };
    if (result.error === STRATEGY_SLUG_TAKEN_MESSAGE) {
      return { status: 'error', errors: { slug: result.error }, values };
    }
    return formError(result.error, values);
  }
  revalidatePath(PAGE);
  // Outside any try: redirect() throws NEXT_REDIRECT, which must reach Next.
  redirect(`${PAGE}?saved=${encodeURIComponent(slug)}`);
}

export async function deleteStrategyAction(
  _previous: StrategyRowState,
  formData: FormData
): Promise<StrategyRowState> {
  const slug = readSlug(formData.get('slug'));
  if (slug === null) return { status: 'error', message: BAD_SLUG_MESSAGE };
  if (isBuiltinSlug(slug)) return { status: 'error', message: STRATEGY_BUILTIN_MESSAGE };
  const result = await guarded(() => removeStrategy(slug));
  // Already gone (another tab, the CLI) is the outcome the user asked for.
  const alreadyGone = !result.success && result.status === 404;
  if (!result.success && !alreadyGone) return { status: 'error', message: result.error };
  revalidatePath(PAGE);
  // The deleted card unmounts with its state, so the list page announces the outcome instead.
  redirect(`${PAGE}?deleted=${encodeURIComponent(slug)}`);
}
