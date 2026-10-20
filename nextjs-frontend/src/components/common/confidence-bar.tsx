const MIN = 0;
const MAX = 100;

export interface ConfidenceBarProps {
  /** Confidence in percent. Clamped to 0-100; missing or non-finite shows "N/A". */
  value?: number | null;
  label?: string;
}

function normalise(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return Math.round(Math.min(MAX, Math.max(MIN, value)));
}

/** A progress bar with the value also written out, so the number never depends on the fill. */
export function ConfidenceBar({ value, label = 'Confidence' }: ConfidenceBarProps) {
  const percent = normalise(value);
  const text = percent === null ? 'N/A' : `${percent}%`;

  if (percent === null) {
    return (
      <div className="flex items-center gap-2">
        <div
          role="img"
          aria-label="Confidence not available"
          className="h-2 w-24 rounded-full bg-secondary"
        />
        <span className="text-sm text-foreground">{text}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={MIN}
        aria-valuemax={MAX}
        aria-valuenow={percent}
        aria-valuetext={text}
        className="h-2 w-24 overflow-hidden rounded-full bg-secondary"
      >
        <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
      <span className="text-sm tabular-nums text-foreground">{text}</span>
    </div>
  );
}
