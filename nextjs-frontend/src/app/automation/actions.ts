'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';

import { addSchedule, editSchedule, removeSchedule, runSchedule } from '@/lib/api/schedules';
import { SCHEDULES_REQUEST_FAILED_MESSAGE } from '@/lib/api/schedules-messages';
import { parseScheduleForm, parseScheduleId, readValues } from '@/lib/automation/form';
import type { FormState, RowState } from '@/lib/automation/state';

/**
 * Server actions for the automation page. Only allow-listed form fields are read and validated
 * (see `lib/automation/form.ts`); the API is reached through the server-only wrappers, and every
 * failure comes back as one of their fixed messages.
 */

const PAGE = '/automation';
const BAD_ID_MESSAGE = 'That schedule id is not valid.';
const BAD_REQUEST_MESSAGE = 'That request is not valid.';

function rowError(message: string): RowState {
  return { status: 'error', message };
}

type Outcome<T> = { success: true; data: T } | { success: false; error: string };

/** Runs a wrapper call; anything it throws becomes the generic fixed message. */
async function guarded<T>(call: () => Promise<Outcome<T>>): Promise<Outcome<T>> {
  try {
    return await call();
  } catch {
    return { success: false, error: SCHEDULES_REQUEST_FAILED_MESSAGE };
  }
}

/** Create (no `id` field) or update (`id` field) a schedule from the form. */
export async function saveScheduleAction(
  _previous: FormState,
  formData: FormData
): Promise<FormState> {
  const rawId = formData.get('id');
  const editing = rawId !== null && rawId !== '';
  const id = editing ? parseScheduleId(rawId) : null;
  if (editing && id === null) {
    return { status: 'error', message: BAD_ID_MESSAGE, errors: {}, values: readValues(formData) };
  }

  const parsed = parseScheduleForm(formData);
  if (!parsed.ok) {
    return { status: 'error', errors: parsed.errors, values: parsed.values };
  }

  const result = await guarded(() =>
    id === null ? addSchedule(parsed.body) : editSchedule(id, parsed.body)
  );
  if (!result.success) {
    return { status: 'error', message: result.error, errors: {}, values: readValues(formData) };
  }
  revalidatePath(PAGE);
  if (id !== null) redirect(PAGE);
  return { status: 'success', message: `Schedule "${parsed.body.name}" created.` };
}

export async function toggleScheduleAction(
  _previous: RowState,
  formData: FormData
): Promise<RowState> {
  const id = parseScheduleId(formData.get('id'));
  if (id === null) return rowError(BAD_ID_MESSAGE);
  const flag = formData.get('enabled');
  if (flag !== 'true' && flag !== 'false') return rowError(BAD_REQUEST_MESSAGE);
  const enabled = flag === 'true';
  const result = await guarded(() => editSchedule(id, { enabled }));
  if (!result.success) return rowError(result.error);
  revalidatePath(PAGE);
  return { status: 'success', message: enabled ? 'Schedule enabled.' : 'Schedule disabled.' };
}

export async function runScheduleAction(
  _previous: RowState,
  formData: FormData
): Promise<RowState> {
  const id = parseScheduleId(formData.get('id'));
  if (id === null) return rowError(BAD_ID_MESSAGE);
  const result = await guarded(() => runSchedule(id));
  if (!result.success) return rowError(result.error);
  revalidatePath(PAGE);
  const run = result.data;
  if (run.status === 'failed') {
    return rowError('The run failed. Open the job log for details.');
  }
  return {
    status: 'success',
    message: `Run finished: ${run.rows} hits, ${run.delivered} delivered, ${run.skipped} skipped.`,
  };
}

export async function deleteScheduleAction(
  _previous: RowState,
  formData: FormData
): Promise<RowState> {
  const id = parseScheduleId(formData.get('id'));
  if (id === null) return rowError(BAD_ID_MESSAGE);
  const result = await guarded(() => removeSchedule(id));
  if (!result.success) return rowError(result.error);
  revalidatePath(PAGE);
  return { status: 'success', message: 'Schedule deleted.' };
}
