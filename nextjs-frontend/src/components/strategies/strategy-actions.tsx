'use client';

import Link from 'next/link';
import { useActionState, useRef, useState, type KeyboardEvent } from 'react';

import { deleteStrategyAction } from '@/app/strategies/actions';
import { Button } from '@/components/ui/button';
import { backtestHref } from '@/lib/backtests/routes';
import { IDLE_STRATEGY_ROW_STATE } from '@/lib/strategies/state';

/**
 * A strategy's actions: scan with it, backtest it, duplicate it and, for a custom one, edit and
 * delete it.
 * Delete asks for confirmation first (Cancel has the initial focus, Escape cancels, focus returns
 * to Delete). A successful delete redirects to the list, which announces it; a failure is
 * announced here in an always-present alert region.
 */

type StrategyActionsProps = { slug: string; name: string; builtin: boolean };

export function StrategyActions({ slug, name, builtin }: StrategyActionsProps) {
  const [deleteState, deleteAction, deleting] = useActionState(
    deleteStrategyAction,
    IDLE_STRATEGY_ROW_STATE
  );
  const [confirming, setConfirming] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const encoded = encodeURIComponent(slug);
  const confirmId = `strategy-${slug}-confirm-delete`;

  const cancelDelete = () => {
    setConfirming(false);
    deleteButton.current?.focus();
  };
  const onConfirmKeyDown = (event: KeyboardEvent<HTMLFormElement>) => {
    if (event.key === 'Escape') cancelDelete();
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        <Button variant="outline" size="sm" asChild>
          <Link href={`/scan?strategy=${encoded}`} aria-label={`Scan with this strategy: ${name}`}>
            Scan with this strategy
          </Link>
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link href={backtestHref(slug)} aria-label={`Backtest: ${name}`}>
            Backtest
          </Link>
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/strategies/new?from=${encoded}`} aria-label={`Duplicate: ${name}`}>
            Duplicate
          </Link>
        </Button>
        {!builtin && (
          <>
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/strategies/${encoded}/edit`} aria-label={`Edit: ${name}`}>
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
              aria-controls={confirming ? confirmId : undefined}
              onClick={() => setConfirming(true)}
            >
              Delete
            </Button>
          </>
        )}
      </div>
      {confirming && (
        <form
          id={confirmId}
          action={deleteAction}
          onKeyDown={onConfirmKeyDown}
          aria-label={`Confirm delete: ${name}`}
          className="flex flex-wrap items-center gap-1 text-sm"
        >
          <input type="hidden" name="slug" value={slug} />
          <span>Delete “{name}”? Schedules using it fall back to SMC default.</span>
          <Button type="button" variant="ghost" size="sm" onClick={cancelDelete} autoFocus>
            Cancel
          </Button>
          <Button type="submit" variant="destructive" size="sm" disabled={deleting}>
            {deleting ? 'Deleting…' : 'Confirm delete'}
          </Button>
        </form>
      )}
      <div role="alert" className="text-xs text-crit-foreground">
        {deleteState.status === 'error' && deleteState.message}
      </div>
    </div>
  );
}
