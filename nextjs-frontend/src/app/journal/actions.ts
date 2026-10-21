'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';

import { addJournalEntry, editJournalEntry, removeJournalEntry } from '@/lib/api/journal';
import { JOURNAL_REQUEST_FAILED_MESSAGE } from '@/lib/api/journal-messages';
import { parseJournalForm, parseJournalId, readJournalValues } from '@/lib/journal/form';
import type { JournalFormState, JournalRowState } from '@/lib/journal/state';

/**
 * Server actions for the journal. Only allow-listed form fields are read and validated (see
 * `lib/journal/form.ts`); the API is reached through the server-only wrappers, and every failure
 * comes back as one of their fixed messages.
 */

const PAGE = '/journal';
const BAD_ID_MESSAGE = 'That entry id is not valid.';

type Outcome<T> = { success: true; data: T } | { success: false; error: string };

/** Runs a wrapper call; anything it throws becomes the generic fixed message. */
async function guarded<T>(call: () => Promise<Outcome<T>>): Promise<Outcome<T>> {
  try {
    return await call();
  } catch {
    return { success: false, error: JOURNAL_REQUEST_FAILED_MESSAGE };
  }
}

/** Create (no `id` field) or update (`id` field) an entry from the form, then back to the list. */
export async function saveJournalAction(
  _previous: JournalFormState,
  formData: FormData
): Promise<JournalFormState> {
  const rawId = formData.get('id');
  const editing = rawId !== null && rawId !== '';
  const id = editing ? parseJournalId(rawId) : null;
  if (editing && id === null) {
    return {
      status: 'error',
      message: BAD_ID_MESSAGE,
      errors: {},
      values: readJournalValues(formData),
    };
  }

  const parsed = parseJournalForm(formData);
  if (!parsed.ok) {
    return { status: 'error', errors: parsed.errors, values: parsed.values };
  }

  const result = await guarded(() =>
    id === null ? addJournalEntry(parsed.body) : editJournalEntry(id, parsed.body)
  );
  if (!result.success) {
    return {
      status: 'error',
      message: result.error,
      errors: {},
      values: readJournalValues(formData),
    };
  }
  revalidatePath(PAGE);
  redirect(PAGE);
}

export async function deleteJournalAction(
  _previous: JournalRowState,
  formData: FormData
): Promise<JournalRowState> {
  const id = parseJournalId(formData.get('id'));
  if (id === null) return { status: 'error', message: BAD_ID_MESSAGE };
  const result = await guarded(() => removeJournalEntry(id));
  if (!result.success) return { status: 'error', message: result.error };
  revalidatePath(PAGE);
  return { status: 'success', message: 'Entry deleted.' };
}
