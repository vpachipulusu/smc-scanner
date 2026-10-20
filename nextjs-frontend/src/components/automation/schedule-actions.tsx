'use client';

import Link from 'next/link';
import { useActionState, useEffect, useRef, useState, type KeyboardEvent } from 'react';

import {
  deleteScheduleAction,
  runScheduleAction,
  toggleScheduleAction,
} from '@/app/automation/actions';
import { Button } from '@/components/ui/button';
import type { ScheduleOut } from '@/lib/api/schedules';
import { IDLE_ROW_STATE, type RowState } from '@/lib/automation/state';

/**
 * Row actions: enable/disable, run now, logs, edit and delete. Delete asks for confirmation first
 * (Cancel has the initial focus, Escape cancels, focus returns to Delete). Results are announced in
 * an always-present polite live region; messages are the fixed ones from the actions.
 */

const PAGE_HEADING_ID = 'automation-heading';

function latestMessage(...states: RowState[]): RowState {
  return (
    states.find((state) => state.status === 'error') ??
    states.find((state) => state.status === 'success') ??
    IDLE_ROW_STATE
  );
}

export function ScheduleActions({ schedule }: { schedule: ScheduleOut }) {
  const [toggleState, toggleAction, toggling] = useActionState(
    toggleScheduleAction,
    IDLE_ROW_STATE
  );
  const [runState, runAction, running] = useActionState(runScheduleAction, IDLE_ROW_STATE);
  const [deleteState, deleteAction, deleting] = useActionState(
    deleteScheduleAction,
    IDLE_ROW_STATE
  );
  const [confirming, setConfirming] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const { id, name, enabled } = schedule;

  // The row disappears once the delete is revalidated; move focus somewhere that stays.
  useEffect(() => {
    if (deleteState.status === 'success') document.getElementById(PAGE_HEADING_ID)?.focus();
  }, [deleteState.status]);

  const cancelDelete = () => {
    setConfirming(false);
    deleteButton.current?.focus();
  };
  const onConfirmKeyDown = (event: KeyboardEvent<HTMLFormElement>) => {
    if (event.key === 'Escape') cancelDelete();
  };

  const message = latestMessage(toggleState, runState, deleteState);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        <form action={toggleAction}>
          <input type="hidden" name="id" value={id} />
          <input type="hidden" name="enabled" value={String(!enabled)} />
          <Button
            type="submit"
            variant="outline"
            size="sm"
            aria-label={`${enabled ? 'Disable' : 'Enable'}: ${name}`}
            disabled={toggling}
          >
            {enabled ? 'Disable' : 'Enable'}
          </Button>
        </form>
        <form action={runAction}>
          <input type="hidden" name="id" value={id} />
          <Button
            type="submit"
            variant="outline"
            size="sm"
            aria-label={`Run now: ${name}`}
            disabled={running}
          >
            {running ? 'Running…' : 'Run now'}
          </Button>
        </form>
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/automation/${id}/logs`} aria-label={`Logs: ${name}`}>
            Logs
          </Link>
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/automation?edit=${id}`} aria-label={`Edit: ${name}`}>
            Edit
          </Link>
        </Button>
        <Button
          ref={deleteButton}
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Delete: ${name}`}
          aria-expanded={confirming}
          onClick={() => setConfirming(true)}
        >
          Delete
        </Button>
      </div>
      {confirming && (
        <form
          action={deleteAction}
          onKeyDown={onConfirmKeyDown}
          aria-label={`Confirm delete: ${name}`}
          className="flex flex-wrap items-center gap-1 text-sm"
        >
          <input type="hidden" name="id" value={id} />
          <span>Delete “{name}” and its job log?</span>
          <Button type="button" variant="ghost" size="sm" onClick={cancelDelete} autoFocus>
            Cancel
          </Button>
          <Button type="submit" variant="destructive" size="sm" disabled={deleting}>
            {deleting ? 'Deleting…' : 'Confirm delete'}
          </Button>
        </form>
      )}
      <div
        role={message.status === 'error' ? 'alert' : 'status'}
        aria-live={message.status === 'error' ? 'assertive' : 'polite'}
        className={
          message.status === 'error'
            ? 'text-xs text-crit-foreground'
            : 'text-xs text-muted-foreground'
        }
      >
        {running && 'Running…'}
        {message.status !== 'idle' && message.message}
      </div>
    </div>
  );
}
