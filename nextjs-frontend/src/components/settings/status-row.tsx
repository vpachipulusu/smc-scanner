import { StatusPill } from '@/components/ui/status-pill';

/** One read-only status line: a label and a pill. Never receives a secret value, only a flag. */
export function StatusRow({
  label,
  on,
  onText,
  offText,
}: {
  label: string;
  on: boolean;
  onText: string;
  offText: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b py-3 last:border-0">
      <dt className="text-sm font-medium">{label}</dt>
      <dd>
        <StatusPill variant={on ? 'good' : 'warn'}>{on ? onText : offText}</StatusPill>
      </dd>
    </div>
  );
}
