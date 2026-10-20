import { ActionPill, type ActionPillAction } from '@/components/common/action-pill';
import { ConfidenceBar } from '@/components/common/confidence-bar';

/** A verdict as the dashboard shows it. Local shape: the Analyses API client is not wired in yet. */
export type VerdictItem = {
  instrument: string;
  action: ActionPillAction;
  confidence?: number | null;
};

export function VerdictList({ items }: { items: readonly VerdictItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No verdicts yet.</p>;
  }
  return (
    <ul className="divide-y">
      {items.map((item) => (
        <li key={item.instrument} className="flex flex-wrap items-center gap-3 py-2">
          <span className="min-w-20 font-medium">{item.instrument}</span>
          <ActionPill action={item.action} />
          <ConfidenceBar value={item.confidence} />
        </li>
      ))}
    </ul>
  );
}
