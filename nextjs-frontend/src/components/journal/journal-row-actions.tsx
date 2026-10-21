'use client';

import Link from 'next/link';
import { useActionState, useRef, useState, type KeyboardEvent } from 'react';

import { deleteJournalAction } from '@/app/journal/actions';
import { Button } from '@/components/ui/button';
import type { JournalEntryOut } from '@/lib/api/journal';
import { JOURNAL_HEADING_ID } from '@/lib/journal/ids';
import { IDLE_JOURNAL_ROW_STATE } from '@/lib/journal/state';

/**
 * Row actions: edit and delete. Delete asks for confirmation first (Cancel has the initial focus,
 * Escape cancels, focus returns to Delete). Results are announced in an always-present live
 * region; messages are the fixed ones from the action.
 */

export function JournalRowActions({ entry }: { entry: JournalEntryOut }) {
  const [state, action, deleting] = useActionState(deleteJournalAction, IDLE_JOURNAL_ROW_STATE);
  const [confirming, setConfirming] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const label = entry.symbol;

  // The row (and this live region) disappears once the delete is revalidated, so focus moves to
  // the page heading as the delete is submitted, before the row unmounts.
  const moveFocusToHeading = () => document.getElementById(JOURNAL_HEADING_ID)?.focus();

  const cancelDelete = () => {
    setConfirming(false);
    deleteButton.current?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLFormElement>) => {
    if (event.key === 'Escape') cancelDelete();
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/journal/${entry.id}/edit`} aria-label={`Edit: ${label}`}>
            Edit
          </Link>
        </Button>
        <Button
          ref={deleteButton}
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Delete: ${label}`}
          aria-expanded={confirming}
          onClick={() => setConfirming(true)}
        >
          Delete
        </Button>
      </div>
      {confirming && (
        <form
          action={action}
          onSubmit={moveFocusToHeading}
          onKeyDown={onKeyDown}
          aria-label={`Confirm delete: ${label}`}
          className="flex flex-wrap items-center gap-1 text-sm"
        >
          <input type="hidden" name="id" value={entry.id} />
          <span>Delete this {label} entry?</span>
          <Button type="button" variant="ghost" size="sm" onClick={cancelDelete} autoFocus>
            Cancel
          </Button>
          <Button type="submit" variant="destructive" size="sm" disabled={deleting}>
            {deleting ? 'Deleting…' : 'Confirm delete'}
          </Button>
        </form>
      )}
      <div
        role={state.status === 'error' ? 'alert' : 'status'}
        aria-live={state.status === 'error' ? 'assertive' : 'polite'}
        className={
          state.status === 'error'
            ? 'text-xs text-crit-foreground'
            : 'text-xs text-muted-foreground'
        }
      >
        {state.status !== 'idle' && state.message}
      </div>
    </div>
  );
}
