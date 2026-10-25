import type { FieldErrors, StrategyFormValues } from './form';

/**
 * State of the strategy form after a submit (useActionState). Success redirects, so there is no
 * success state. `values` may lack `conditions` when the catalogue could not be read.
 */
export type StrategyFormState =
  | { status: 'idle' }
  | { status: 'error'; message?: string; errors: FieldErrors; values: StrategyFormValues };

/** State of the delete action. Success redirects to the list, which announces it. */
export type StrategyRowState = { status: 'idle' } | { status: 'error'; message: string };

export const IDLE_STRATEGY_FORM_STATE: StrategyFormState = { status: 'idle' };
export const IDLE_STRATEGY_ROW_STATE: StrategyRowState = { status: 'idle' };
