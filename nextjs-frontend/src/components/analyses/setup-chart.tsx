import { useId } from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AiVerdict, AnalysisOut } from '@/lib/api/analyses';
import { formatPrice, isFiniteNumber, numberList } from './format';

const WIDTH = 360;
const HEIGHT = 220;
const PAD_Y = 16;
const LABEL_X = 8;

type Kind = 'entry' | 'stop' | 'target';
type Level = { kind: Kind; label: string; price: number };

/** Entry is solid, stop dashed, targets dotted: the lines differ by shape, not only by position. */
const DASH: Record<Kind, string | undefined> = {
  entry: undefined,
  stop: '6 4',
  target: '2 4',
};

function levelsOf(verdict: AiVerdict): Level[] {
  const levels: Level[] = [];
  if (isFiniteNumber(verdict.entry)) {
    levels.push({ kind: 'entry', label: 'Entry', price: verdict.entry });
  }
  if (isFiniteNumber(verdict.stop)) {
    levels.push({ kind: 'stop', label: 'Stop', price: verdict.stop });
  }
  numberList(verdict.targets).forEach((price, index) => {
    levels.push({ kind: 'target', label: `T${index + 1}`, price });
  });
  return levels;
}

const LABEL_GAP = 13;

/** Label baselines pushed apart so close levels do not draw their text over each other. */
function spreadLabels(ys: readonly number[]): number[] {
  const order = ys.map((_, i) => i).sort((a, b) => ys[a] - ys[b]);
  const out = [...ys];
  let previous = Number.NEGATIVE_INFINITY;
  for (const i of order) {
    out[i] = Math.max(ys[i], previous + LABEL_GAP);
    previous = out[i];
  }
  return out;
}

function describe(zone: [number, number] | null, levels: readonly Level[]): string {
  const parts: string[] = [];
  if (zone) parts.push(`Zone ${formatPrice(zone[0])} to ${formatPrice(zone[1])}`);
  for (const level of levels) {
    const word = level.kind === 'target' ? 'target' : level.kind;
    parts.push(`${word} ${formatPrice(level.price)}`);
  }
  return `${parts.join(', ')}.`;
}

/**
 * The zone as a band and the verdict's entry, stop and targets as lines on one price axis. The API
 * returns no candles, so this is a price ladder rather than a candle chart. A written description
 * of every level is attached as the text alternative.
 */
export function SetupChart({ analysis, verdict }: { analysis: AnalysisOut; verdict: AiVerdict }) {
  const id = useId();
  const levels = levelsOf(verdict);
  const zone: [number, number] | null =
    isFiniteNumber(analysis.zone_low) && isFiniteNumber(analysis.zone_high)
      ? [
          Math.min(analysis.zone_low, analysis.zone_high),
          Math.max(analysis.zone_low, analysis.zone_high),
        ]
      : null;
  const prices = [...levels.map((l) => l.price), ...(zone ?? [])];
  if (prices.length === 0) return null;

  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const margin = (high - low) * 0.1 || Math.abs(high) * 0.01 || 1;
  const top = high + margin;
  const bottom = low - margin;
  const y = (price: number) => PAD_Y + ((top - price) / (top - bottom)) * (HEIGHT - 2 * PAD_Y);

  const labelYs = spreadLabels(levels.map((level) => y(level.price) - 4));
  const titleId = `${id}-title`;
  const descId = `${id}-desc`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Zone and levels</CardTitle>
      </CardHeader>
      <CardContent>
        <svg
          role="img"
          aria-labelledby={titleId}
          aria-describedby={descId}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto w-full max-w-xl text-foreground"
        >
          <title id={titleId}>{`${analysis.symbol} ${analysis.tf} zone and trade levels`}</title>
          {zone && (
            <g>
              <rect
                x={0}
                y={y(zone[1])}
                width={WIDTH}
                height={Math.max(y(zone[0]) - y(zone[1]), 2)}
                fill="currentColor"
                opacity={0.2}
              />
              <text
                x={LABEL_X}
                y={y(zone[1]) + 12}
                fontSize={11}
                fill="currentColor"
                aria-hidden="true"
              >
                Zone
              </text>
            </g>
          )}
          {levels.map((level, index) => (
            <g key={`${level.kind}-${index}`} aria-hidden="true">
              <line
                x1={0}
                x2={WIDTH}
                y1={y(level.price)}
                y2={y(level.price)}
                stroke="currentColor"
                strokeWidth={level.kind === 'entry' ? 2 : 1.5}
                strokeDasharray={DASH[level.kind]}
              />
              <text
                x={WIDTH - LABEL_X}
                y={labelYs[index]}
                fontSize={11}
                textAnchor="end"
                fill="currentColor"
              >
                {`${level.label} ${formatPrice(level.price)}`}
              </text>
            </g>
          ))}
        </svg>
        <p id={descId} className="sr-only">
          {describe(zone, levels)}
        </p>
      </CardContent>
    </Card>
  );
}
