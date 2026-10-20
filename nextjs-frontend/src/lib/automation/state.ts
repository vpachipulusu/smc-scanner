import type { FieldErrors, FormValues } from './form';

/** State of the schedule form after a submit (useActionState). */
export type FormState =
  | { status: 'idle' }
  | { status: 'error'; message?: string; errors: FieldErrors; values: FormValues }
  | { status: 'success'; message: string };

/** State of a row action (toggle, run now, delete): a short message to announce. */
export type RowState =
  | { status: 'idle' }
  | { status: 'success'; message: string }
  | { status: 'error'; message: string };

export const IDLE_FORM_STATE: FormState = { status: 'idle' };
export const IDLE_ROW_STATE: RowState = { status: 'idle' };
