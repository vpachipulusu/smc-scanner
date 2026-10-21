import type { JournalFieldErrors, JournalFormValues } from './form';

/** State of the journal form after a submit (useActionState). Success redirects, so no state. */
export type JournalFormState =
  | { status: 'idle' }
  | { status: 'error'; message?: string; errors: JournalFieldErrors; values: JournalFormValues };

/** State of a row action (delete): a short message to announce. */
export type JournalRowState =
  | { status: 'idle' }
  | { status: 'success'; message: string }
  | { status: 'error'; message: string };

export const IDLE_JOURNAL_FORM_STATE: JournalFormState = { status: 'idle' };
export const IDLE_JOURNAL_ROW_STATE: JournalRowState = { status: 'idle' };
