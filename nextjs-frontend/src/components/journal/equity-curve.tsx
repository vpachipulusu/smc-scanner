import { useId } from 'react';

import { downsample, equityGeometry } from '@/lib/journal/equity';
import { formatRValue, type CumulativePoint } from '@/lib/journal/stats';
import { formatUtc } from '@/components/analyses/format';

const BOX = { width: 640, height: 220, padding: 16 };

/**
 * Cumulative R after each closed trade, as a hand-written SVG line. The drawing is for sighted
 * users; the table beside it carries the same numbers for screen readers.
 */
export function EquityCurve({ points }: { points: ReadonlyArray<CumulativePoint> }) {
  const titleId = useId();
  const descId = useId();
  if (points.length === 0) return null;

  const shown = downsample(points);
  const geometry = equityGeometry(shown, BOX);
  const last = shown[shown.length - 1];

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        className="h-auto w-full text-primary"
      >
        <title id={titleId}>Equity curve</title>
        <desc id={descId}>
          {`Cumulative R over ${points.length} closed ${points.length === 1 ? 'trade' : 'trades'}, ending at ${formatRValue(last.cumulative_r)}.`}
        </desc>
        <line
          x1={BOX.padding}
          x2={BOX.width - BOX.padding}
          y1={geometry.baselineY}
          y2={geometry.baselineY}
          className="stroke-border"
          strokeDasharray="4 4"
        />
        <path
          d={geometry.path}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {geometry.points.length === 1 && (
          <circle cx={geometry.points[0].x} cy={geometry.points[0].y} r={3} fill="currentColor" />
        )}
      </svg>
      <figcaption className="text-xs text-muted-foreground">
        Cumulative R after each closed trade; the dashed line is zero.
      </figcaption>
      <table className="sr-only">
        <caption>Cumulative R by closed trade</caption>
        <thead>
          <tr>
            <th scope="col">Closed</th>
            <th scope="col">Trade R</th>
            <th scope="col">Cumulative R</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((point) => (
            <tr key={point.entry_id}>
              <td>{formatUtc(point.closed_at)}</td>
              <td>{formatRValue(point.r)}</td>
              <td>{formatRValue(point.cumulative_r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
