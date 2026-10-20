import { ActionPill, type ActionPillAction } from '@/components/common/action-pill';
import { ConfidenceBar } from '@/components/common/confidence-bar';
import { StatusPill } from '@/components/ui/status-pill';

/** A stored analysis as the dashboard shows it. `action` is null when the analysis failed. */
export type VerdictItem = {
  id: number;
  symbol: string;
  tf: string;
  createdAt: string;
  action: ActionPillAction | null;
  confidence?: number | null;
  /** True when the analysis itself failed; false with a null action means it stored no verdict. */
  failed?: boolean;
};

function When({ iso }: { iso: string }) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return <span>{iso}</span>;
  return <time dateTime={iso}>{`${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`}</time>;
}

/**
 * One row per verdict. The detail page (/analyses/[id]) does not exist yet, so the id is plain
 * text rather than a link that would 404.
 */
export function VerdictList({ items }: { items: readonly VerdictItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No verdicts yet.</p>;
  }
  return (
    <>
      <ul className="divide-y">
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-3 py-2">
            <span className="min-w-20 font-medium">{item.symbol}</span>
            <span className="text-sm text-muted-foreground">{item.tf}</span>
            {item.action ? (
              <>
                <ActionPill action={item.action} />
                <ConfidenceBar value={item.confidence} />
              </>
            ) : (
              <StatusPill variant={item.failed ? 'warn' : 'neutral'}>
                {item.failed ? 'Analysis failed' : 'No verdict'}
              </StatusPill>
            )}
            <span className="w-full text-sm text-muted-foreground sm:ml-auto sm:w-auto">
              <When iso={item.createdAt} />
              <span aria-hidden="true"> · </span>
              <span>#{item.id}</span>
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
